#include <gtest/gtest.h>
#include <sys/wait.h>

#include <algorithm>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <sstream>
#include <string>
#include <vector>

#include "itch_bytes.hpp"
#include "qlob/replay.hpp"

using namespace qlob;
namespace fs = std::filesystem;

namespace {
std::vector<std::byte> mixed_day() {
  std::vector<std::byte> buf;
  itch_bytes::append_frame(buf, itch_bytes::add(7, 100, 1, 'B', 300, "AAPL", 150'0000));
  itch_bytes::append_frame(buf, itch_bytes::add_mpid(7, 200, 2, 'S', 400, "AAPL", 150'0100, "GSCO"));
  itch_bytes::append_frame(buf, itch_bytes::system_event(0, 250, 'Q'));
  itch_bytes::append_frame(buf, itch_bytes::del(7, 300, 1));
  itch_bytes::append_frame(buf, itch_bytes::del(7, 400, 99));
  return buf;
}

std::string header_of(std::size_t depth) {
  std::ostringstream out;
  replay({}, depth, &out);
  return out.str();
}
}  // namespace

TEST(WriteCounts, EmitsNonZeroTypeCountsAndAlwaysTheFramingKeysSortedByKey) {
  FrameReport r;
  r.counts['D'] = 1;
  r.counts['A'] = 2;
  r.length_mismatch['A'] = 3;
  r.unknown_type = 4;
  r.empty_frames = 5;
  r.first_bad_offset = 42;
  r.trailing_bytes = 6;
  std::ostringstream out;
  write_counts(r, out);
  EXPECT_EQ(out.str(),
            "count_A=2\n"
            "count_D=1\n"
            "empty_frames=5\n"
            "first_bad_offset=42\n"
            "length_mismatch_A=3\n"
            "trailing_bytes=6\n"
            "unknown_type=4\n");
}

TEST(WriteCounts, CleanEmptyReportWritesNoneForFirstBadOffset) {
  std::ostringstream out;
  write_counts(FrameReport{}, out);
  EXPECT_EQ(out.str(),
            "empty_frames=0\n"
            "first_bad_offset=none\n"
            "trailing_bytes=0\n"
            "unknown_type=0\n");
}

TEST(Replay, WritesOneSnapshotRowPerDecodedBookEventIncludingUnknownRefs) {
  const auto buf = mixed_day();
  std::ostringstream out;
  replay(buf, 2, &out);
  EXPECT_EQ(out.str(),
            "seq,ts_ns,bid_px1,bid_qty1,ask_px1,ask_qty1,bid_px2,bid_qty2,ask_px2,ask_qty2\n"
            "0,100,1500000,300,0,0,0,0,0,0\n"
            "1,200,1500000,300,1500100,400,0,0,0,0\n"
            "2,300,0,0,1500100,400,0,0,0,0\n"
            "3,400,0,0,1500100,400,0,0,0,0\n");
}

TEST(Replay, WritesRowsForExecuteCancelAndReplaceEvents) {
  std::vector<std::byte> buf;
  itch_bytes::append_frame(buf, itch_bytes::add(7, 100, 1, 'B', 300, "AAPL", 150'0000));
  itch_bytes::append_frame(buf, itch_bytes::add(7, 200, 2, 'S', 400, "AAPL", 150'0100));
  itch_bytes::append_frame(buf, itch_bytes::exec(7, 300, 1, 100, 1));
  itch_bytes::append_frame(buf, itch_bytes::exec_price(7, 400, 2, 50, 2, 'Y', 999));
  itch_bytes::append_frame(buf, itch_bytes::cancel(7, 500, 1, 25));
  itch_bytes::append_frame(buf, itch_bytes::replace(7, 600, 2, 3, 80, 150'0200));
  itch_bytes::append_frame(buf, itch_bytes::exec(7, 700, 2, 5, 3));
  itch_bytes::append_frame(buf, itch_bytes::cancel(7, 800, 1, 500));
  std::ostringstream out;
  const auto r = replay(buf, 1, &out);
  EXPECT_EQ(out.str(),
            "seq,ts_ns,bid_px1,bid_qty1,ask_px1,ask_qty1\n"
            "0,100,1500000,300,0,0\n"
            "1,200,1500000,300,1500100,400\n"
            "2,300,1500000,200,1500100,400\n"
            "3,400,1500000,200,1500100,350\n"
            "4,500,1500000,175,1500100,350\n"
            "5,600,1500000,175,1500200,80\n"
            "6,700,1500000,175,1500200,80\n"
            "7,800,0,0,1500200,80\n");
  EXPECT_EQ(r.stats.events, 8u);
  EXPECT_EQ(r.stats.unknown_order_refs, 1u);
  EXPECT_EQ(r.stats.excess_reductions, 1u);
}

TEST(Replay, ReturnsBookStatsAndTrailingBytes) {
  auto buf = mixed_day();
  buf.push_back(std::byte{0x00});  // half a length prefix
  const auto r = replay(buf, 2, nullptr);
  EXPECT_EQ(r.stats.events, 4u);
  EXPECT_EQ(r.stats.unknown_order_refs, 1u);
  EXPECT_EQ(r.stats.duplicate_order_refs, 0u);
  EXPECT_EQ(r.trailing_bytes, 1u);
}

TEST(Replay, BookMessagesThatFailToDecodeAreCountedAndProduceNoRows) {
  auto short_add = itch_bytes::add(7, 150, 5, 'B', 10, "AAPL", 150'0000);
  short_add.pop_back();
  auto long_exec = itch_bytes::exec(7, 160, 1, 10, 1);
  long_exec.push_back(std::byte{0});
  const auto bad_side = itch_bytes::add(7, 170, 6, 'Z', 10, "AAPL", 150'0000);

  std::vector<std::byte> buf;
  itch_bytes::append_frame(buf, itch_bytes::add(7, 100, 1, 'B', 300, "AAPL", 150'0000));
  itch_bytes::append_frame(buf, short_add);
  itch_bytes::append_frame(buf, long_exec);
  itch_bytes::append_frame(buf, bad_side);
  itch_bytes::append_frame(buf, itch_bytes::system_event(0, 180, 'Q'));
  itch_bytes::append_frame(buf, itch_bytes::del(7, 200, 1));
  std::ostringstream out;
  const auto r = replay(buf, 1, &out);
  EXPECT_EQ(out.str(),
            "seq,ts_ns,bid_px1,bid_qty1,ask_px1,ask_qty1\n"
            "0,100,1500000,300,0,0\n"
            "1,200,0,0,0,0\n");
  EXPECT_EQ(r.decode_rejects, 3u);
  EXPECT_EQ(r.stats.events, 2u);
  EXPECT_EQ(r.stats.unknown_order_refs, 0u);
}

TEST(Replay, NonBookAndEmptyFramesAreNotDecodeRejects) {
  std::vector<std::byte> buf;
  itch_bytes::append_frame(buf, itch_bytes::system_event(0, 100, 'Q'));
  itch_bytes::append_frame(buf, {});
  itch_bytes::append_frame(buf, {std::byte{'Z'}, std::byte{0}});
  EXPECT_EQ(replay(buf, 1, nullptr).decode_rejects, 0u);
}

TEST(Replay, HeaderWidthFollowsDepth) {
  EXPECT_EQ(header_of(1), "seq,ts_ns,bid_px1,bid_qty1,ask_px1,ask_qty1\n");
  EXPECT_EQ(header_of(3),
            "seq,ts_ns,bid_px1,bid_qty1,ask_px1,ask_qty1,bid_px2,bid_qty2,ask_px2,ask_qty2,"
            "bid_px3,bid_qty3,ask_px3,ask_qty3\n");
}

TEST(WriteSummary, EmitsBookStatsAndTrailingBytesSortedByKey) {
  ReplayResult r;
  r.stats.events = 1;
  r.stats.unknown_order_refs = 2;
  r.stats.duplicate_order_refs = 3;
  r.stats.excess_reductions = 4;
  r.stats.zero_qty_adds = 5;
  r.trailing_bytes = 6;
  r.decode_rejects = 7;
  r.stats.exec_not_at_front = 8;
  r.stats.exec_with_price_not_at_front = 9;
  std::ostringstream out;
  write_summary(r, out);
  EXPECT_EQ(out.str(),
            "decode_rejects=7\n"
            "duplicate_order_refs=3\n"
            "events=1\n"
            "excess_reductions=4\n"
            "exec_not_at_front=8\n"
            "exec_with_price_not_at_front=9\n"
            "trailing_bytes=6\n"
            "unknown_order_refs=2\n"
            "zero_qty_adds=5\n");
}

// CLI: exercise the built binary end to end (exact exit codes and streams).
namespace {
struct Run { int code; std::string out, err; };

std::string slurp(const fs::path& p) {
  std::ifstream in(p, std::ios::binary);
  return {std::istreambuf_iterator<char>(in), {}};
}

// Per-test paths so parallel ctest processes never share files; removed on scope exit.
class TempPath {
 public:
  explicit TempPath(const std::string& suffix)
      : path_(fs::path(testing::TempDir()) /
              (std::string("qlob_") + testing::UnitTest::GetInstance()->current_test_info()->name() +
               suffix)) {}
  ~TempPath() {
    std::error_code ec;
    fs::remove(path_, ec);
  }
  TempPath(const TempPath&) = delete;
  TempPath& operator=(const TempPath&) = delete;
  const fs::path& path() const { return path_; }
  std::string quoted() const { return "'" + path_.string() + "'"; }

 private:
  fs::path path_;
};

// Paths are single-quoted for /bin/sh; they must not themselves contain a single quote.
Run run_cli(const std::string& args) {
  const TempPath out(".out"), err(".err");
  const std::string cmd = std::string("'") + QLOB_REPLAY_PATH + "' " + args + " >" + out.quoted() +
                          " 2>" + err.quoted();
  const int status = std::system(cmd.c_str());
  return {WIFEXITED(status) ? WEXITSTATUS(status) : -1, slurp(out.path()), slurp(err.path())};
}

struct Fixture : TempPath {
  explicit Fixture(const std::vector<std::byte>& bytes) : TempPath(".itch") {
    std::ofstream f(path(), std::ios::binary);
    f.write(reinterpret_cast<const char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
  }
};
}  // namespace

TEST(Cli, NoArgumentsIsUsageError) {
  const auto r = run_cli("");
  EXPECT_EQ(r.code, 2);
  EXPECT_NE(r.err.find("usage"), std::string::npos);
}

TEST(Cli, UnreadableFileExitsTwo) {
  EXPECT_EQ(run_cli("/nonexistent/qlob.itch").code, 2);
}

TEST(Cli, DirectoryIsReportedAsNotARegularFile) {
  const auto r = run_cli("'" + testing::TempDir() + "'");
  EXPECT_EQ(r.code, 2);
  EXPECT_NE(r.err.find("not a regular file"), std::string::npos) << r.err;
}

TEST(Cli, BadDepthIsUsageError) {
  const Fixture f(mixed_day());
  EXPECT_EQ(run_cli(f.quoted() + " --depth 0").code, 2);
  EXPECT_EQ(run_cli(f.quoted() + " --depth x").code, 2);
  EXPECT_EQ(run_cli(f.quoted() + " --depth").code, 2);
}

TEST(Cli, DepthIsCappedAtOneThousand) {
  const Fixture f(mixed_day());
  EXPECT_EQ(run_cli(f.quoted() + " --depth 1000").code, 0);
  EXPECT_EQ(run_cli(f.quoted() + " --depth 1001").code, 2);
}

TEST(Cli, CountWithSnapshotsIsUsageError) {
  const Fixture f(mixed_day());
  EXPECT_EQ(run_cli(f.quoted() + " --count --snapshots -").code, 2);
}

TEST(Cli, StreamsSnapshotsToStdoutAndSummaryToStderr) {
  const Fixture f(mixed_day());
  const auto r = run_cli(f.quoted() + " --depth 1 --snapshots -");
  EXPECT_EQ(r.code, 0);
  EXPECT_EQ(r.out,
            "seq,ts_ns,bid_px1,bid_qty1,ask_px1,ask_qty1\n"
            "0,100,1500000,300,0,0\n"
            "1,200,1500000,300,1500100,400\n"
            "2,300,0,0,1500100,400\n"
            "3,400,0,0,1500100,400\n");
  EXPECT_EQ(r.err,
            "decode_rejects=0\nduplicate_order_refs=0\nevents=4\nexcess_reductions=0\nexec_not_at_front=0\nexec_with_price_not_at_front=0\ntrailing_bytes=0\n"
            "unknown_order_refs=1\nzero_qty_adds=0\n");
}

TEST(Cli, WritesSnapshotsToFile) {
  const Fixture f(mixed_day());
  const TempPath csv(".csv");
  const auto r = run_cli(f.quoted() + " --snapshots " + csv.quoted());
  EXPECT_EQ(r.code, 0);
  EXPECT_TRUE(r.out.empty());
  const auto text = slurp(csv.path());
  EXPECT_EQ(text.substr(0, text.find('\n') + 1), header_of(5));
  EXPECT_EQ(std::count(text.begin(), text.end(), '\n'), 5);
}

TEST(Cli, CountModePrintsFrameReport) {
  const Fixture f(mixed_day());
  const auto r = run_cli(f.quoted() + " --count");
  EXPECT_EQ(r.code, 0);
  EXPECT_EQ(r.out,
            "count_A=1\ncount_D=2\ncount_F=1\ncount_S=1\nempty_frames=0\n"
            "first_bad_offset=none\ntrailing_bytes=0\nunknown_type=0\n");
}

TEST(Cli, EmptyFileIsNotAnError) {
  const Fixture f({});
  const auto r = run_cli(f.quoted() + " --count");
  EXPECT_EQ(r.code, 0);
  EXPECT_EQ(r.out, "empty_frames=0\nfirst_bad_offset=none\ntrailing_bytes=0\nunknown_type=0\n");
  EXPECT_EQ(run_cli(f.quoted()).code, 0);
}
