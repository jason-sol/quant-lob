#include "qlob/replay.hpp"

#include <cstdint>
#include <limits>
#include <ostream>
#include <map>
#include <string>

namespace qlob {
namespace {
using Lines = std::map<std::string, std::string>;

void write_lines(const Lines& lines, std::ostream& out) {
  for (const auto& [key, value] : lines) out << key << '=' << value << '\n';
}

void write_header(std::size_t depth, std::ostream& out) {
  out << "seq,ts_ns";
  for (std::size_t i = 1; i <= depth; ++i) {
    out << ",bid_px" << i << ",bid_qty" << i << ",ask_px" << i << ",ask_qty" << i;
  }
  out << '\n';
}

void write_row(std::uint64_t seq, std::uint64_t ts_ns, const Snapshot& s, std::ostream& out) {
  out << seq << ',' << ts_ns;
  for (std::size_t i = 0; i < s.bids.size(); ++i) {
    out << ',' << s.bids[i].price << ',' << s.bids[i].qty << ',' << s.asks[i].price << ','
        << s.asks[i].qty;
  }
  out << '\n';
}
}  // namespace

void write_counts(const FrameReport& report, std::ostream& out) {
  Lines lines;
  for (std::size_t t = 0; t < report.counts.size(); ++t) {
    const char type = static_cast<char>(t);
    if (report.counts[t] > 0) lines[std::string("count_") + type] = std::to_string(report.counts[t]);
    if (report.length_mismatch[t] > 0) {
      lines[std::string("length_mismatch_") + type] = std::to_string(report.length_mismatch[t]);
    }
  }
  lines["unknown_type"] = std::to_string(report.unknown_type);
  lines["empty_frames"] = std::to_string(report.empty_frames);
  lines["trailing_bytes"] = std::to_string(report.trailing_bytes);
  lines["first_bad_offset"] = report.first_bad_offset == std::numeric_limits<std::size_t>::max()
                                  ? "none"
                                  : std::to_string(report.first_bad_offset);
  write_lines(lines, out);
}

ReplayResult replay(std::span<const std::byte> buf, std::size_t depth, std::ostream* snapshots) {
  if (snapshots) write_header(depth, *snapshots);
  Book book;
  std::uint64_t seq = 0, decode_rejects = 0;
  const auto status = for_each_frame(buf, [&](std::span<const std::byte> msg, std::size_t) {
    const auto ev = decode(msg);
    if (!ev) {
      if (!msg.empty() && is_book_type(std::to_integer<unsigned char>(msg[0]))) ++decode_rejects;
      return;
    }
    book.apply(*ev);
    if (snapshots) write_row(seq, ev->ts_ns, book.snapshot(depth), *snapshots);
    ++seq;
  });
  return {book.stats(), status.trailing_bytes, decode_rejects};
}

void write_summary(const ReplayResult& result, std::ostream& out) {
  const auto& s = result.stats;
  write_lines({{"decode_rejects", std::to_string(result.decode_rejects)},
               {"duplicate_order_refs", std::to_string(s.duplicate_order_refs)},
               {"events", std::to_string(s.events)},
               {"exec_not_at_front", std::to_string(s.exec_not_at_front)},
               {"exec_with_price_not_at_front", std::to_string(s.exec_with_price_not_at_front)},
               {"excess_reductions", std::to_string(s.excess_reductions)},
               {"trailing_bytes", std::to_string(result.trailing_bytes)},
               {"unknown_order_refs", std::to_string(s.unknown_order_refs)},
               {"zero_qty_adds", std::to_string(s.zero_qty_adds)}},
              out);
}
}  // namespace qlob
