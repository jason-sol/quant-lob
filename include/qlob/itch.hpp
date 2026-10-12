#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <optional>
#include <span>
#include "qlob/event.hpp"

namespace qlob {
std::optional<Event> decode(std::span<const std::byte> msg);  // nullopt: empty, non-book, wrong length, invalid side
std::size_t expected_length(unsigned char type);              // 0 = unknown type

struct FrameStatus { std::size_t trailing_bytes = 0; };

template <class F>
FrameStatus for_each_frame(std::span<const std::byte> buf, F&& on_msg) {
  std::size_t pos = 0;
  while (pos + 2 <= buf.size()) {
    const auto len = (std::to_integer<std::size_t>(buf[pos]) << 8) |
                     std::to_integer<std::size_t>(buf[pos + 1]);
    if (pos + 2 + len > buf.size()) break;
    on_msg(buf.subspan(pos + 2, len), pos);
    pos += 2 + len;
  }
  return {buf.size() - pos};
}

struct FrameReport {
  std::array<std::uint64_t, 256> counts{};
  std::array<std::uint64_t, 256> length_mismatch{};
  std::uint64_t unknown_type = 0, empty_frames = 0;
  std::size_t first_bad_offset = std::numeric_limits<std::size_t>::max();
  std::size_t trailing_bytes = 0;
};
// Validates framing only: a frame scan calls clean can still fail decode (e.g. bad side byte).
FrameReport scan(std::span<const std::byte> buf);
}  // namespace qlob
