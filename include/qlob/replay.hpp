#pragma once
#include <cstddef>
#include <cstdint>
#include <iosfwd>
#include <span>

#include "qlob/book.hpp"
#include "qlob/itch.hpp"

namespace qlob {
struct ReplayResult {
  BookStats stats;
  std::size_t trailing_bytes = 0;
  std::uint64_t decode_rejects = 0;  // book message type that failed to decode: no Event, no row
};

void write_counts(const FrameReport& report, std::ostream& out);

// Applies every decoded book Event to a fresh Book. With `snapshots`, writes a CSV header
// then one Snapshot row (top `depth` Price levels) per decoded book Event.
ReplayResult replay(std::span<const std::byte> buf, std::size_t depth, std::ostream* snapshots);

void write_summary(const ReplayResult& result, std::ostream& out);
}  // namespace qlob
