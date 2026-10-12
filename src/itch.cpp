#include "qlob/itch.hpp"

namespace qlob {
namespace {

constexpr std::array<std::uint8_t, 256> kExpectedLength = [] {
  std::array<std::uint8_t, 256> t{};
  t['S'] = 12; t['R'] = 39; t['H'] = 25; t['Y'] = 20; t['L'] = 26; t['V'] = 35;
  t['W'] = 12; t['K'] = 28; t['J'] = 35; t['h'] = 21; t['A'] = 36; t['F'] = 40;
  t['E'] = 31; t['C'] = 36; t['X'] = 23; t['D'] = 19; t['U'] = 35; t['P'] = 44;
  t['Q'] = 40; t['B'] = 19; t['I'] = 50; t['N'] = 20; t['O'] = 48;
  return t;
}();

constexpr std::uint64_t be(const std::byte* p, std::size_t n) {
  std::uint64_t v = 0;
  for (std::size_t i = 0; i < n; ++i) v = (v << 8) | std::to_integer<std::uint64_t>(p[i]);
  return v;
}

Event order_header(EventType type, const std::byte* p) {
  Event ev{};
  ev.type = type;
  ev.locate = static_cast<std::uint16_t>(be(p + 1, 2));
  ev.ts_ns = be(p + 5, 6);
  ev.order_id = be(p + 11, 8);
  return ev;
}

}  // namespace

std::size_t expected_length(unsigned char type) { return kExpectedLength[type]; }

bool is_book_type(unsigned char type) {
  switch (type) {
    case 'A': case 'F': case 'E': case 'C': case 'X': case 'D': case 'U': return true;
    default: return false;
  }
}

// Decodes the book messages A, F, E, C, X, D and U.
std::optional<Event> decode(std::span<const std::byte> msg) {
  if (msg.empty()) return std::nullopt;
  const auto type = std::to_integer<unsigned char>(msg[0]);
  if (msg.size() != expected_length(type)) return std::nullopt;
  const std::byte* p = msg.data();

  switch (type) {
    case 'A':
    case 'F': {
      // A side byte other than 'B'/'S' is malformed: the message is dropped, not guessed.
      const auto side = std::to_integer<char>(p[19]);
      if (side != 'B' && side != 'S') return std::nullopt;
      Event ev = order_header(EventType::Add, p);
      ev.side = side == 'B' ? Side::Buy : Side::Sell;
      ev.qty = static_cast<std::uint32_t>(be(p + 20, 4));
      ev.price = static_cast<Price>(be(p + 32, 4));
      return ev;
    }
    case 'E':
    case 'C': {
      // C's execution price can differ from the resting price; the Book uses the resting price.
      Event ev = order_header(type == 'E' ? EventType::Execute : EventType::ExecuteWithPrice, p);
      ev.qty = static_cast<std::uint32_t>(be(p + 19, 4));
      return ev;
    }
    case 'X': {
      Event ev = order_header(EventType::Cancel, p);
      ev.qty = static_cast<std::uint32_t>(be(p + 19, 4));
      return ev;
    }
    case 'D':
      return order_header(EventType::Delete, p);
    case 'U': {
      Event ev = order_header(EventType::Replace, p);
      ev.new_order_id = be(p + 19, 8);
      ev.qty = static_cast<std::uint32_t>(be(p + 27, 4));
      ev.price = static_cast<Price>(be(p + 31, 4));
      return ev;
    }
    default:
      return std::nullopt;
  }
}

FrameReport scan(std::span<const std::byte> buf) {
  FrameReport rep;
  auto flag = [&](std::size_t offset) {
    if (rep.first_bad_offset == std::numeric_limits<std::size_t>::max()) rep.first_bad_offset = offset;
  };
  rep.trailing_bytes = for_each_frame(buf, [&](std::span<const std::byte> msg, std::size_t offset) {
    if (msg.empty()) {
      ++rep.empty_frames;
      flag(offset);
      return;
    }
    const auto type = std::to_integer<unsigned char>(msg[0]);
    ++rep.counts[type];
    const std::size_t want = expected_length(type);
    if (want == 0) {
      ++rep.unknown_type;
      flag(offset);
    } else if (msg.size() != want) {
      ++rep.length_mismatch[type];
      flag(offset);
    }
  }).trailing_bytes;
  return rep;
}

}  // namespace qlob
