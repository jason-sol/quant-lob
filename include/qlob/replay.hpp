#pragma once
#include <cstddef>
#include <iosfwd>
#include <span>

#include "qlob/book.hpp"
#include "qlob/itch.hpp"

namespace qlob {
struct ReplayResult {
  BookStats stats;
  std::size_t trailing_bytes = 0;
};

void write_counts(const FrameReport& report, std::ostream& out);

// Applies every decoded book Event to a fresh Book. With `snapshots`, writes a CSV header
// then one Snapshot row (top `depth` Price levels) per decoded book Event.
ReplayResult replay(std::span<const std::byte> buf, std::size_t depth, std::ostream* snapshots);

void write_summary(const ReplayResult& result, std::ostream& out);
}  // namespace qlob
