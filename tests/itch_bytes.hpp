#pragma once
// Builders for raw ITCH 5.0 messages (big-endian, offsets from the type byte).
#include <cstddef>
#include <cstdint>
#include <string_view>
#include <vector>

namespace itch_bytes {

inline void put_be(std::vector<std::byte>& buf, std::uint64_t value, int nbytes) {
  for (int i = nbytes - 1; i >= 0; --i) {
    buf.push_back(static_cast<std::byte>((value >> (8 * i)) & 0xFF));
  }
}

inline void put_alpha(std::vector<std::byte>& buf, std::string_view s, std::size_t width) {
  for (std::size_t i = 0; i < width; ++i) {
    buf.push_back(static_cast<std::byte>(i < s.size() ? s[i] : ' '));
  }
}

inline std::vector<std::byte> header(char type, std::uint16_t locate, std::uint64_t ts) {
  std::vector<std::byte> buf;
  buf.push_back(static_cast<std::byte>(type));
  put_be(buf, locate, 2);
  put_be(buf, 0, 2);  // tracking number
  put_be(buf, ts, 6);
  return buf;
}

inline std::vector<std::byte> add(std::uint16_t locate, std::uint64_t ts, std::uint64_t ref,
                                  char side, std::uint32_t shares, std::string_view stock,
                                  std::uint32_t price) {
  auto buf = header('A', locate, ts);
  put_be(buf, ref, 8);
  buf.push_back(static_cast<std::byte>(side));
  put_be(buf, shares, 4);
  put_alpha(buf, stock, 8);
  put_be(buf, price, 4);
  return buf;
}

inline std::vector<std::byte> add_mpid(std::uint16_t locate, std::uint64_t ts, std::uint64_t ref,
                                       char side, std::uint32_t shares, std::string_view stock,
                                       std::uint32_t price, std::string_view mpid) {
  auto buf = add(locate, ts, ref, side, shares, stock, price);
  buf[0] = static_cast<std::byte>('F');
  put_alpha(buf, mpid, 4);
  return buf;
}

inline std::vector<std::byte> del(std::uint16_t locate, std::uint64_t ts, std::uint64_t ref) {
  auto buf = header('D', locate, ts);
  put_be(buf, ref, 8);
  return buf;
}

inline std::vector<std::byte> exec(std::uint16_t locate, std::uint64_t ts, std::uint64_t ref,
                                   std::uint32_t shares, std::uint64_t match) {
  auto buf = header('E', locate, ts);
  put_be(buf, ref, 8);
  put_be(buf, shares, 4);
  put_be(buf, match, 8);
  return buf;
}

inline std::vector<std::byte> exec_price(std::uint16_t locate, std::uint64_t ts, std::uint64_t ref,
                                         std::uint32_t shares, std::uint64_t match, char printable,
                                         std::uint32_t price) {
  auto buf = exec(locate, ts, ref, shares, match);
  buf[0] = static_cast<std::byte>('C');
  buf.push_back(static_cast<std::byte>(printable));
  put_be(buf, price, 4);
  return buf;
}

inline std::vector<std::byte> cancel(std::uint16_t locate, std::uint64_t ts, std::uint64_t ref,
                                     std::uint32_t shares) {
  auto buf = header('X', locate, ts);
  put_be(buf, ref, 8);
  put_be(buf, shares, 4);
  return buf;
}

inline std::vector<std::byte> replace(std::uint16_t locate, std::uint64_t ts, std::uint64_t old_ref,
                                      std::uint64_t new_ref, std::uint32_t shares,
                                      std::uint32_t price) {
  auto buf = header('U', locate, ts);
  put_be(buf, old_ref, 8);
  put_be(buf, new_ref, 8);
  put_be(buf, shares, 4);
  put_be(buf, price, 4);
  return buf;
}

inline std::vector<std::byte> system_event(std::uint16_t locate, std::uint64_t ts, char code) {
  auto buf = header('S', locate, ts);
  buf.push_back(static_cast<std::byte>(code));
  return buf;
}

inline void append_frame(std::vector<std::byte>& buf, const std::vector<std::byte>& msg) {
  put_be(buf, msg.size(), 2);
  buf.insert(buf.end(), msg.begin(), msg.end());
}

}  // namespace itch_bytes
