#include <gtest/gtest.h>
#include <cstdint>
#include <cstring>
#include <limits>
#include <map>
#include <memory>
#include "itch_bytes.hpp"
#include "qlob/itch.hpp"

using namespace qlob;

TEST(Itch, DecodesAddOrder) {
  auto msg = itch_bytes::add(7, 34'200'000'000'123ULL, 42, 'B', 100, "AAPL", 1'523'400);
  auto ev = decode(msg);
  ASSERT_TRUE(ev);
  EXPECT_EQ(ev->type, EventType::Add);
  EXPECT_EQ(ev->locate, 7);
  EXPECT_EQ(ev->ts_ns, 34'200'000'000'123ULL);
  EXPECT_EQ(ev->order_id, 42u);
  EXPECT_EQ(ev->side, Side::Buy);
  EXPECT_EQ(ev->qty, 100u);
  EXPECT_EQ(ev->price, 1'523'400u);
}

TEST(Itch, DecodesAddWithMpidLikeAdd) {
  auto ev = decode(itch_bytes::add_mpid(7, 1, 43, 'S', 5, "AAPL", 1'523'500, "GSCO"));
  ASSERT_TRUE(ev);
  EXPECT_EQ(ev->side, Side::Sell);
  EXPECT_EQ(ev->order_id, 43u);
}

TEST(Itch, DecodesAddWithMpidQtyAndPrice) {
  auto ev = decode(itch_bytes::add_mpid(7, 1, 43, 'S', 0x01020304u, "AAPL", 0x0A0B0C0Du, "GSCO"));
  ASSERT_TRUE(ev);
  EXPECT_EQ(ev->type, EventType::Add);
  EXPECT_EQ(ev->qty, 0x01020304u);
  EXPECT_EQ(ev->price, 0x0A0B0C0Du);
}

TEST(Itch, DecodesDelete) {
  auto ev = decode(itch_bytes::del(7, 2, 42));
  ASSERT_TRUE(ev);
  EXPECT_EQ(ev->type, EventType::Delete);
  EXPECT_EQ(ev->order_id, 42u);
}

TEST(Itch, DecodesDeleteLocateAndTimestamp) {
  auto ev = decode(itch_bytes::del(0x0A0B, 0x010203040506ULL, 42));
  ASSERT_TRUE(ev);
  EXPECT_EQ(ev->locate, 0x0A0B);
  EXPECT_EQ(ev->ts_ns, 0x010203040506ULL);
}

TEST(Itch, NonBookMessageDecodesToNullopt) {
  EXPECT_FALSE(decode(itch_bytes::system_event(0, 1, 'O')));
}

TEST(Itch, EmptyMessageIsRejectedNotRead) {
  EXPECT_FALSE(decode(std::span<const std::byte>{}));
}

TEST(Itch, ValidatorFlagsShortKnownTypeWithOffset) {
  std::vector<std::byte> buf;
  itch_bytes::append_frame(buf, itch_bytes::add(7, 1, 1, 'B', 1, "AAPL", 1));
  auto shortAdd = itch_bytes::add(7, 1, 2, 'B', 1, "AAPL", 1);
  shortAdd.resize(20);
  itch_bytes::append_frame(buf, shortAdd);
  FrameReport rep = scan(buf);
  EXPECT_EQ(rep.counts['A'], 2u);
  EXPECT_EQ(rep.length_mismatch['A'], 1u);
  EXPECT_EQ(rep.first_bad_offset, 2u + 36u);
}

TEST(Itch, FrameIteratorReportsTruncatedPrefixAndBody) {
  std::vector<std::byte> buf;
  itch_bytes::append_frame(buf, itch_bytes::del(7, 2, 1));
  auto partial = buf;
  itch_bytes::append_frame(partial, itch_bytes::del(7, 3, 2));
  partial.resize(partial.size() - 5);
  std::size_t frames = 0;
  auto status = for_each_frame(partial, [&](std::span<const std::byte>, std::size_t) { ++frames; });
  EXPECT_EQ(frames, 1u);
  EXPECT_EQ(status.trailing_bytes, 2u + 19u - 5u);
}

TEST(Itch, FrameIteratorPassesPrefixOffsetOfEachFrame) {
  std::vector<std::byte> buf;
  itch_bytes::append_frame(buf, itch_bytes::del(7, 1, 1));
  itch_bytes::append_frame(buf, itch_bytes::system_event(0, 2, 'O'));
  itch_bytes::append_frame(buf, itch_bytes::add(7, 3, 2, 'B', 1, "AAPL", 1));
  std::vector<std::size_t> offsets;
  for_each_frame(buf, [&](std::span<const std::byte>, std::size_t off) { offsets.push_back(off); });
  EXPECT_EQ(offsets, (std::vector<std::size_t>{0, 2 + 19, 2 + 19 + 2 + 12}));
}

TEST(Itch, DecodeRejectsShortAdd) {
  auto msg = itch_bytes::add(7, 1, 42, 'B', 100, "AAPL", 1);
  msg.pop_back();
  EXPECT_FALSE(decode(msg));
}

TEST(Itch, DecodeRejectsLongAdd) {
  auto msg = itch_bytes::add(7, 1, 42, 'B', 100, "AAPL", 1);
  msg.push_back(std::byte{0});
  EXPECT_FALSE(decode(msg));
}

TEST(Itch, DecodeRejectsShortDelete) {
  auto msg = itch_bytes::del(7, 1, 42);
  msg.pop_back();
  EXPECT_FALSE(decode(msg));
}

TEST(Itch, DecodeRejectsAddWithUnknownSideByte) {
  EXPECT_FALSE(decode(itch_bytes::add(7, 1, 42, 'X', 100, "AAPL", 1)));
}

TEST(Itch, DecodeAssemblesEveryFieldBigEndian) {
  auto ev = decode(itch_bytes::add(0x0102, 0x0A0B0C0D0E0FULL, 0x0102030405060708ULL, 'S',
                                   0x11223344u, "AAPL", 0x55667788u));
  ASSERT_TRUE(ev);
  EXPECT_EQ(ev->locate, 0x0102);
  EXPECT_EQ(ev->ts_ns, 0x0A0B0C0D0E0FULL);
  EXPECT_EQ(ev->order_id, 0x0102030405060708ULL);
  EXPECT_EQ(ev->qty, 0x11223344u);
  EXPECT_EQ(ev->price, 0x55667788u);
}

TEST(Itch, ExpectedLengthMatchesSpecForEveryTypeByte) {
  const std::map<unsigned char, std::size_t> spec{
      {'S', 12}, {'R', 39}, {'H', 25}, {'Y', 20}, {'L', 26}, {'V', 35}, {'W', 12}, {'K', 28},
      {'J', 35}, {'h', 21}, {'A', 36}, {'F', 40}, {'E', 31}, {'C', 36}, {'X', 23}, {'D', 19},
      {'U', 35}, {'P', 44}, {'Q', 40}, {'B', 19}, {'I', 50}, {'N', 20}, {'O', 48}};
  ASSERT_EQ(spec.size(), 23u);
  for (int b = 0; b < 256; ++b) {
    const auto type = static_cast<unsigned char>(b);
    const auto it = spec.find(type);
    EXPECT_EQ(expected_length(type), it == spec.end() ? 0u : it->second) << "type byte " << b;
  }
}

TEST(Itch, ScanOfCleanBufferHasNoBadOffset) {
  std::vector<std::byte> buf;
  itch_bytes::append_frame(buf, itch_bytes::system_event(0, 1, 'O'));
  itch_bytes::append_frame(buf, itch_bytes::del(7, 2, 1));
  FrameReport rep = scan(buf);
  EXPECT_EQ(rep.counts['S'], 1u);
  EXPECT_EQ(rep.counts['D'], 1u);
  EXPECT_EQ(rep.first_bad_offset, std::numeric_limits<std::size_t>::max());
  EXPECT_EQ(rep.trailing_bytes, 0u);
}

TEST(Itch, ScanCountsUnknownTypeAndEmptyFrameWithoutReadingPastFrame) {
  std::vector<std::byte> v;
  itch_bytes::append_frame(v, itch_bytes::del(7, 2, 1));
  const std::size_t unknown_at = v.size();
  itch_bytes::append_frame(v, {std::byte{'z'}, std::byte{0}, std::byte{0}});
  itch_bytes::append_frame(v, {});  // empty frame last: msg[0] would be out of bounds

  // Exact-size heap copy so ASan traps any read past the final byte.
  auto exact = std::make_unique<std::byte[]>(v.size());
  std::memcpy(exact.get(), v.data(), v.size());
  FrameReport rep = scan({exact.get(), v.size()});

  EXPECT_EQ(rep.counts['D'], 1u);
  EXPECT_EQ(rep.counts['z'], 1u);
  EXPECT_EQ(rep.unknown_type, 1u);
  EXPECT_EQ(rep.length_mismatch['z'], 0u);
  EXPECT_EQ(rep.empty_frames, 1u);
  EXPECT_EQ(rep.first_bad_offset, unknown_at);
}

TEST(Itch, ScanFlagsTooLongKnownFrame) {
  std::vector<std::byte> buf;
  auto long_del = itch_bytes::del(7, 1, 1);
  long_del.push_back(std::byte{0});
  itch_bytes::append_frame(buf, long_del);
  FrameReport rep = scan(buf);
  EXPECT_EQ(rep.counts['D'], 1u);
  EXPECT_EQ(rep.length_mismatch['D'], 1u);
  EXPECT_EQ(rep.first_bad_offset, 0u);
}

TEST(Itch, ScanFlagsLengthMismatchOnNonBookType) {
  std::vector<std::byte> buf;
  itch_bytes::append_frame(buf, itch_bytes::del(7, 1, 1));
  auto short_sys = itch_bytes::system_event(0, 1, 'O');
  short_sys.pop_back();
  itch_bytes::append_frame(buf, short_sys);
  FrameReport rep = scan(buf);
  EXPECT_EQ(rep.counts['S'], 1u);
  EXPECT_EQ(rep.length_mismatch['S'], 1u);
  EXPECT_EQ(rep.unknown_type, 0u);
  EXPECT_EQ(rep.first_bad_offset, 2u + 19u);
}

TEST(Itch, ScanReportsTrailingBytesOfTruncatedPrefix) {
  std::vector<std::byte> buf;
  itch_bytes::append_frame(buf, itch_bytes::del(7, 2, 1));
  buf.push_back(std::byte{0});
  EXPECT_EQ(scan(buf).trailing_bytes, 1u);
}

TEST(Itch, ScanReportsEmptyFrameOffsetWhenItIsFirstBad) {
  std::vector<std::byte> buf;
  itch_bytes::append_frame(buf, itch_bytes::del(7, 2, 1));
  itch_bytes::append_frame(buf, {});
  FrameReport rep = scan(buf);
  EXPECT_EQ(rep.empty_frames, 1u);
  EXPECT_EQ(rep.first_bad_offset, 2u + 19u);
}

namespace {
// Distinct bytes per field, so a wrong offset or byte order shows up as a wrong value.
constexpr std::uint16_t kLocate = 0x0102;
constexpr std::uint64_t kTs = 0x030405060708ULL;
constexpr std::uint64_t kRef = 0x1112131415161718ULL;
constexpr std::uint64_t kNewRef = 0x5152535455565758ULL;
constexpr std::uint32_t kShares = 0x21222324u;
constexpr std::uint64_t kMatch = 0x3132333435363738ULL;
constexpr std::uint32_t kPrice = 0x41424344u;

void expect_header(const Event& ev) {
  EXPECT_EQ(ev.locate, kLocate);
  EXPECT_EQ(ev.ts_ns, kTs);
  EXPECT_EQ(ev.order_id, kRef);
}
}  // namespace

TEST(Itch, BuildersProduceSpecLengths) {
  EXPECT_EQ(itch_bytes::exec(kLocate, kTs, kRef, kShares, kMatch).size(), 31u);
  EXPECT_EQ(itch_bytes::exec_price(kLocate, kTs, kRef, kShares, kMatch, 'Y', kPrice).size(), 36u);
  EXPECT_EQ(itch_bytes::cancel(kLocate, kTs, kRef, kShares).size(), 23u);
  EXPECT_EQ(itch_bytes::replace(kLocate, kTs, kRef, kNewRef, kShares, kPrice).size(), 35u);
}

TEST(Itch, DecodesExecutedAsExecuteWithExecutedShares) {
  auto ev = decode(itch_bytes::exec(kLocate, kTs, kRef, kShares, kMatch));
  ASSERT_TRUE(ev);
  EXPECT_EQ(ev->type, EventType::Execute);
  expect_header(*ev);
  EXPECT_EQ(ev->qty, kShares);
}

TEST(Itch, DecodesExecutedWithPriceAsExecuteWithShares) {
  auto ev = decode(itch_bytes::exec_price(kLocate, kTs, kRef, kShares, kMatch, 'N', kPrice));
  ASSERT_TRUE(ev);
  EXPECT_EQ(ev->type, EventType::Execute);
  expect_header(*ev);
  EXPECT_EQ(ev->qty, kShares);
}

TEST(Itch, DecodesCancelWithCancelledShares) {
  auto ev = decode(itch_bytes::cancel(kLocate, kTs, kRef, kShares));
  ASSERT_TRUE(ev);
  EXPECT_EQ(ev->type, EventType::Cancel);
  expect_header(*ev);
  EXPECT_EQ(ev->qty, kShares);
}

TEST(Itch, DecodesReplaceWithOriginalAndNewRefSharesAndPrice) {
  auto ev = decode(itch_bytes::replace(kLocate, kTs, kRef, kNewRef, kShares, kPrice));
  ASSERT_TRUE(ev);
  EXPECT_EQ(ev->type, EventType::Replace);
  expect_header(*ev);
  EXPECT_EQ(ev->new_order_id, kNewRef);
  EXPECT_EQ(ev->qty, kShares);
  EXPECT_EQ(ev->price, kPrice);
}

TEST(Itch, DecodeRejectsWrongLengthExecuteCancelReplace) {
  const std::vector<std::vector<std::byte>> msgs{
      itch_bytes::exec(kLocate, kTs, kRef, kShares, kMatch),
      itch_bytes::exec_price(kLocate, kTs, kRef, kShares, kMatch, 'Y', kPrice),
      itch_bytes::cancel(kLocate, kTs, kRef, kShares),
      itch_bytes::replace(kLocate, kTs, kRef, kNewRef, kShares, kPrice)};
  for (const auto& good : msgs) {
    const char type = std::to_integer<char>(good[0]);
    ASSERT_TRUE(decode(good)) << type;
    auto short_msg = good;
    short_msg.pop_back();
    EXPECT_FALSE(decode(short_msg)) << "short " << type;
    auto long_msg = good;
    long_msg.push_back(std::byte{0});
    EXPECT_FALSE(decode(long_msg)) << "long " << type;
  }
}
