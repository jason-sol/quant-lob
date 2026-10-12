#include <gtest/gtest.h>

#include <map>
#include <random>
#include <vector>

#include "qlob/book.hpp"

using namespace qlob;
static Event add(OrderId id, Side s, std::uint32_t q, Price p) { return {EventType::Add, s, 7, 0, id, 0, q, p}; }
static Event del(OrderId id) { return {EventType::Delete, Side::Buy, 7, 0, id, 0, 0, 0}; }

TEST(Book, AggregatesLevelsBestFirstAndPadsDepth) {
  Book b;
  b.apply(add(1, Side::Buy, 100, 100'0000));
  b.apply(add(2, Side::Buy, 50, 100'0000));
  b.apply(add(3, Side::Buy, 10, 99'9900));
  b.apply(add(4, Side::Sell, 70, 100'0100));
  auto s = b.snapshot(2);
  EXPECT_EQ(s.bids[0].price, 100'0000u); EXPECT_EQ(s.bids[0].qty, 150u);
  EXPECT_EQ(s.bids[1].price, 99'9900u);  EXPECT_EQ(s.bids[1].qty, 10u);
  EXPECT_EQ(s.asks[0].price, 100'0100u); EXPECT_EQ(s.asks[0].qty, 70u);
  EXPECT_EQ(s.asks[1].price, 0u);        EXPECT_EQ(s.asks[1].qty, 0u);
}

TEST(Book, DeleteRemovesOrderAndEmptyLevel) {
  Book b;
  b.apply(add(1, Side::Buy, 100, 100'0000));
  b.apply(del(1));
  EXPECT_EQ(b.snapshot(1).bids[0].qty, 0u);
  EXPECT_EQ(b.stats().unknown_order_refs, 0u);
}

TEST(Book, UnknownAndDuplicateRefsAreCounted) {
  Book b;
  b.apply(del(999));
  b.apply(add(1, Side::Buy, 1, 1));
  b.apply(add(1, Side::Sell, 5, 2));
  EXPECT_EQ(b.stats().unknown_order_refs, 1u);
  EXPECT_EQ(b.stats().duplicate_order_refs, 1u);
  EXPECT_EQ(b.snapshot(1).asks[0].qty, 0u);
}

TEST(Book, DetectsCrossedOrLockedBook) {
  Book b;
  b.apply(add(1, Side::Buy, 1, 101'0000));
  b.apply(add(2, Side::Sell, 1, 100'0000));
  EXPECT_TRUE(b.crossed());
}

TEST(Book, DeleteOneOfTwoOrdersKeepsLevelWithReducedTotal) {
  Book b;
  b.apply(add(1, Side::Sell, 30, 100'0100));
  b.apply(add(2, Side::Sell, 45, 100'0100));
  b.apply(del(1));
  auto s = b.snapshot(1);
  EXPECT_EQ(s.asks[0].price, 100'0100u);
  EXPECT_EQ(s.asks[0].qty, 45u);
}

TEST(Book, AsksAreOrderedAscending) {
  Book b;
  b.apply(add(1, Side::Sell, 3, 100'0300));
  b.apply(add(2, Side::Sell, 1, 100'0100));
  b.apply(add(3, Side::Sell, 2, 100'0200));
  auto s = b.snapshot(3);
  EXPECT_EQ(s.asks[0].price, 100'0100u); EXPECT_EQ(s.asks[0].qty, 1u);
  EXPECT_EQ(s.asks[1].price, 100'0200u); EXPECT_EQ(s.asks[1].qty, 2u);
  EXPECT_EQ(s.asks[2].price, 100'0300u); EXPECT_EQ(s.asks[2].qty, 3u);
}

TEST(Book, SnapshotDeeperThanBookIsPaddedOnBothSides) {
  Book b;
  b.apply(add(1, Side::Buy, 5, 99'0000));
  auto s = b.snapshot(4);
  ASSERT_EQ(s.bids.size(), 4u);
  ASSERT_EQ(s.asks.size(), 4u);
  EXPECT_EQ(s.bids[0].price, 99'0000u);
  for (std::size_t i = 1; i < 4; ++i) {
    EXPECT_EQ(s.bids[i].price, 0u); EXPECT_EQ(s.bids[i].qty, 0u);
  }
  for (const auto& lv : s.asks) {
    EXPECT_EQ(lv.price, 0u); EXPECT_EQ(lv.qty, 0u);
  }
}

TEST(Book, LockedBookCountsAsCrossed) {
  Book b;
  b.apply(add(1, Side::Buy, 1, 100'0000));
  b.apply(add(2, Side::Sell, 1, 100'0000));
  EXPECT_TRUE(b.crossed());
}

TEST(Book, NormalSpreadIsNotCrossed) {
  Book b;
  b.apply(add(1, Side::Buy, 1, 100'0000));
  b.apply(add(2, Side::Sell, 1, 100'0100));
  EXPECT_FALSE(b.crossed());
}

TEST(Book, EmptyOrOneSidedBookIsNotCrossed) {
  Book b;
  EXPECT_FALSE(b.crossed());
  b.apply(add(1, Side::Sell, 1, 100'0000));
  EXPECT_FALSE(b.crossed());
}

TEST(Book, EveryAppliedEventIsCounted) {
  Book b;
  b.apply(add(1, Side::Buy, 1, 1));
  b.apply(add(1, Side::Buy, 1, 1));
  b.apply(del(2));
  b.apply(del(1));
  EXPECT_EQ(b.stats().events, 4u);
}

TEST(Book, InvariantsHoldAfterAddDeleteSequence) {
  Book b;
  b.apply(add(1, Side::Buy, 10, 100'0000));
  b.apply(add(2, Side::Buy, 20, 100'0000));
  b.apply(add(3, Side::Sell, 30, 100'0100));
  b.apply(del(1));
  b.apply(del(3));
  EXPECT_NO_THROW(b.check_invariants());
}

TEST(Book, ZeroQuantityAddIsCountedAndIgnored) {
  Book b;
  b.apply(add(1, Side::Buy, 10, 100'0000));
  b.apply(add(2, Side::Buy, 0, 100'0000));
  b.apply(add(3, Side::Sell, 0, 100'0100));
  auto s = b.snapshot(1);
  EXPECT_EQ(s.bids[0].price, 100'0000u); EXPECT_EQ(s.bids[0].qty, 10u);
  EXPECT_EQ(s.asks[0].price, 0u);        EXPECT_EQ(s.asks[0].qty, 0u);
  EXPECT_NO_THROW(b.check_invariants());
  EXPECT_EQ(b.stats().zero_qty_adds, 2u);
  b.apply(del(2));
  EXPECT_EQ(b.stats().unknown_order_refs, 1u);
}

TEST(Book, ZeroQuantityAddOnLiveIdCountsAsDuplicate) {
  Book b;
  b.apply(add(1, Side::Buy, 10, 100'0000));
  b.apply(add(1, Side::Sell, 0, 100'0100));
  EXPECT_EQ(b.stats().duplicate_order_refs, 1u);
  EXPECT_EQ(b.stats().zero_qty_adds, 0u);
  auto s = b.snapshot(1);
  EXPECT_EQ(s.bids[0].price, 100'0000u); EXPECT_EQ(s.bids[0].qty, 10u);
  EXPECT_EQ(s.asks[0].qty, 0u);
}

namespace {
struct Live { Side side; Price price; std::uint32_t qty; };

void expect_side_matches(const std::vector<LevelView>& got,
                         const std::vector<LevelView>& want, const char* side,
                         int step) {
  ASSERT_EQ(got.size(), want.size());
  for (std::size_t i = 0; i < got.size(); ++i) {
    EXPECT_EQ(got[i].price, want[i].price) << side << " level " << i << " step " << step;
    EXPECT_EQ(got[i].qty, want[i].qty) << side << " level " << i << " step " << step;
  }
}
}  // namespace

TEST(Book, RandomAddDeleteMatchesIndependentTally) {
  constexpr std::size_t kDepth = 16;  // exceeds the distinct prices per side below
  std::mt19937 rng(20261012);
  std::uniform_int_distribution<int> coin(0, 99);
  std::uniform_int_distribution<std::uint32_t> qty(1, 500);
  std::uniform_int_distribution<Price> tick(0, 9);

  Book b;
  std::map<OrderId, Live> live;
  std::vector<OrderId> ids;
  std::map<Price, std::uint64_t> bid_tally, ask_tally;
  OrderId next_id = 1;
  std::uint64_t unknown = 0, duplicate = 0, zero_qty = 0;

  for (int step = 0; step < 1000; ++step) {
    int r = coin(rng);
    if (r < 3) {
      b.apply(del(1'000'000 + static_cast<OrderId>(step)));
      ++unknown;
    } else if (r < 6 && !ids.empty()) {
      b.apply(add(ids[ids.size() / 2], Side::Sell, 1, 1));
      ++duplicate;
    } else if (r < 9) {
      Side s = coin(rng) < 50 ? Side::Buy : Side::Sell;
      b.apply(add(next_id++, s, 0, s == Side::Buy ? 99'9100 : 100'0100));
      ++zero_qty;
    } else if (r < 60 || ids.empty()) {
      Side s = coin(rng) < 50 ? Side::Buy : Side::Sell;
      Price p = s == Side::Buy ? 99'9100 + tick(rng) * 100 : 100'0100 + tick(rng) * 100;
      std::uint32_t q = qty(rng);
      OrderId id = next_id++;
      b.apply(add(id, s, q, p));
      live[id] = {s, p, q};
      ids.push_back(id);
      (s == Side::Buy ? bid_tally : ask_tally)[p] += q;
    } else {
      std::size_t k = std::uniform_int_distribution<std::size_t>(0, ids.size() - 1)(rng);
      OrderId id = ids[k];
      ids[k] = ids.back();
      ids.pop_back();
      b.apply(del(id));
      const Live& o = live.at(id);
      auto& tally = o.side == Side::Buy ? bid_tally : ask_tally;
      if ((tally[o.price] -= o.qty) == 0) tally.erase(o.price);
      live.erase(id);
    }

    ASSERT_NO_THROW(b.check_invariants()) << "step " << step;

    std::vector<LevelView> want_bids, want_asks;
    for (auto it = bid_tally.rbegin(); it != bid_tally.rend(); ++it) want_bids.push_back({it->first, it->second});
    for (const auto& [p, q] : ask_tally) want_asks.push_back({p, q});
    constexpr std::size_t kShallow = 3;
    auto shallow_bids = want_bids, shallow_asks = want_asks;
    shallow_bids.resize(kShallow);
    shallow_asks.resize(kShallow);
    auto shallow = b.snapshot(kShallow);
    expect_side_matches(shallow.bids, shallow_bids, "bid", step);
    expect_side_matches(shallow.asks, shallow_asks, "ask", step);
    if (::testing::Test::HasFailure()) return;

    want_bids.resize(kDepth);
    want_asks.resize(kDepth);

    auto s = b.snapshot(kDepth);
    expect_side_matches(s.bids, want_bids, "bid", step);
    expect_side_matches(s.asks, want_asks, "ask", step);
    if (::testing::Test::HasFailure()) return;
  }

  EXPECT_EQ(b.stats().events, 1000u);
  EXPECT_EQ(b.stats().unknown_order_refs, unknown);
  EXPECT_EQ(b.stats().duplicate_order_refs, duplicate);
  EXPECT_GT(unknown, 0u);
  EXPECT_EQ(b.stats().zero_qty_adds, zero_qty);
  EXPECT_GT(duplicate, 0u);
  EXPECT_GT(zero_qty, 0u);
}
