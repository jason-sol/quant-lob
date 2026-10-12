// Random Events of every EventType against the Book and an independent in-test model.
// "Never crossed" is deliberately not asserted: random Events cross legitimately.
#include <gtest/gtest.h>

#include <algorithm>
#include <array>
#include <cstdint>
#include <map>
#include <random>
#include <unordered_map>
#include <utility>
#include <vector>

#include "qlob/book.hpp"

using namespace qlob;

namespace {
constexpr int kEventsPerSeed = 10'000;
constexpr Price kTicks = 20;
constexpr std::size_t kDepth = kTicks;  // every Price in the band fits, so Snapshots cover the whole Book
using LevelKey = std::pair<Side, Price>;

// Live orders, per-side aggregated Price levels and per-level FIFOs, maintained without
// reference to Book.
class Model {
 public:
  void apply(const Event& ev) {
    ++stats.events;
    touched.clear();
    switch (ev.type) {
      case EventType::Add:
        if (live_.contains(ev.order_id)) {
          ++stats.duplicate_order_refs;
        } else if (ev.qty == 0) {
          ++stats.zero_qty_adds;
        } else {
          insert(ev.order_id, {ev.side, ev.price, ev.qty});
        }
        break;
      case EventType::Delete:
        if (!live_.contains(ev.order_id)) {
          ++stats.unknown_order_refs;
        } else {
          drop(ev.order_id);
        }
        break;
      case EventType::Execute:
      case EventType::ExecuteWithPrice:
      case EventType::Cancel: {
        auto it = live_.find(ev.order_id);
        if (it == live_.end()) {
          ++stats.unknown_order_refs;
          break;
        }
        if (fifos_.at({it->second.side, it->second.price}).front() != ev.order_id) {
          if (ev.type == EventType::Execute) ++stats.exec_not_at_front;
          if (ev.type == EventType::ExecuteWithPrice) ++stats.exec_with_price_not_at_front;
        }
        if (ev.qty < it->second.qty) {
          it->second.qty -= ev.qty;
          levels(it->second.side)[it->second.price] -= ev.qty;
          touched.push_back({it->second.side, it->second.price});
        } else {
          if (ev.qty > it->second.qty) ++stats.excess_reductions;
          drop(ev.order_id);
        }
        break;
      }
      case EventType::Replace: {
        auto it = live_.find(ev.order_id);
        if (it == live_.end()) {
          ++stats.unknown_order_refs;
        } else if (live_.contains(ev.new_order_id)) {
          ++stats.duplicate_order_refs;
        } else if (ev.qty == 0) {
          ++stats.zero_qty_adds;
        } else {
          const Side side = it->second.side;
          drop(ev.order_id);
          insert(ev.new_order_id, {side, ev.price, ev.qty});
        }
        break;
      }
    }
  }

  Snapshot snapshot() const {
    Snapshot s{std::vector<LevelView>(kDepth), std::vector<LevelView>(kDepth)};
    std::size_t i = 0;
    for (auto it = bids_.rbegin(); it != bids_.rend() && i < kDepth; ++it, ++i) s.bids[i] = {it->first, it->second};
    i = 0;
    for (auto it = asks_.begin(); it != asks_.end() && i < kDepth; ++it, ++i) s.asks[i] = {it->first, it->second};
    return s;
  }

  bool empty() const { return ids_.empty(); }
  std::size_t size() const { return ids_.size(); }
  OrderId pick(std::mt19937_64& rng) const {
    return ids_[std::uniform_int_distribution<std::size_t>(0, ids_.size() - 1)(rng)];
  }
  std::uint32_t qty_of(OrderId id) const { return live_.at(id).qty; }
  std::vector<OrderId> fifo(LevelKey key) const {
    auto it = fifos_.find(key);
    return it == fifos_.end() ? std::vector<OrderId>{} : it->second;
  }

  BookStats stats;
  std::vector<LevelKey> touched;  // levels the last Event changed

 private:
  struct Order { Side side; Price price; std::uint32_t qty; };

  std::map<Price, std::uint64_t>& levels(Side s) { return s == Side::Buy ? bids_ : asks_; }

  void insert(OrderId id, Order o) {
    live_.emplace(id, o);
    levels(o.side)[o.price] += o.qty;
    auto& q = fifos_[{o.side, o.price}];
    q.insert(std::upper_bound(q.begin(), q.end(), id), id);  // queue priority is by order ref
    touched.push_back({o.side, o.price});
    index_.emplace(id, ids_.size());
    ids_.push_back(id);
  }

  void drop(OrderId id) {
    const Order o = live_.at(id);
    auto& lv = levels(o.side);
    if ((lv[o.price] -= o.qty) == 0) lv.erase(o.price);
    auto& q = fifos_.at({o.side, o.price});
    q.erase(std::find(q.begin(), q.end(), id));
    if (q.empty()) fifos_.erase({o.side, o.price});
    touched.push_back({o.side, o.price});
    live_.erase(id);
    const std::size_t k = index_.at(id);
    index_[ids_.back()] = k;
    ids_[k] = ids_.back();
    ids_.pop_back();
    index_.erase(id);
  }

  std::unordered_map<OrderId, Order> live_;
  std::map<Price, std::uint64_t> bids_, asks_;
  std::map<LevelKey, std::vector<OrderId>> fifos_;
  std::vector<OrderId> ids_;
  std::unordered_map<OrderId, std::size_t> index_;
};

::testing::AssertionResult same_snapshot(const Snapshot& got, const Snapshot& want) {
  auto side = [](const std::vector<LevelView>& g, const std::vector<LevelView>& w, const char* name)
      -> ::testing::AssertionResult {
    if (g.size() != w.size()) return ::testing::AssertionFailure() << name << " depth " << g.size();
    for (std::size_t i = 0; i < g.size(); ++i) {
      if (g[i].price != w[i].price || g[i].qty != w[i].qty) {
        return ::testing::AssertionFailure() << name << " level " << i << ": Book " << g[i].price << "x"
                                             << g[i].qty << ", model " << w[i].price << "x" << w[i].qty;
      }
    }
    return ::testing::AssertionSuccess();
  };
  if (auto r = side(got.bids, want.bids, "bid"); !r) return r;
  return side(got.asks, want.asks, "ask");
}

::testing::AssertionResult same_stats(const BookStats& got, const BookStats& want) {
  if (got.events == want.events && got.unknown_order_refs == want.unknown_order_refs &&
      got.duplicate_order_refs == want.duplicate_order_refs && got.excess_reductions == want.excess_reductions &&
      got.zero_qty_adds == want.zero_qty_adds && got.exec_not_at_front == want.exec_not_at_front &&
      got.exec_with_price_not_at_front == want.exec_with_price_not_at_front) {
    return ::testing::AssertionSuccess();
  }
  return ::testing::AssertionFailure() << "counters differ";
}

class Generator {
 public:
  explicit Generator(std::uint64_t seed) : rng_(seed) {}

  // ~1% of Events are unknown refs, duplicate ids or zero quantities; excess reductions arise separately.
  Event next(const Model& m) {
    const int r = percent();
    if (r == 0) return anomaly(m);
    if (m.empty() || r < 31) return add(add_id(), side(), qty(), price());
    const OrderId id = m.pick(rng_);
    if (r < 51) return {EventType::Delete, Side::Buy, 7, 0, id, 0, 0, 0};
    if (r < 81) {
      const EventType t = r < 61 ? EventType::Execute : r < 71 ? EventType::ExecuteWithPrice : EventType::Cancel;
      return {t, Side::Buy, 7, 0, id, 0, removal(m.qty_of(id)), 0};
    }
    return replace(id, next_id_++, qty(), price());
  }

  std::uint64_t late_adds() const { return late_adds_; }


 private:
  Event anomaly(const Model& m) {
    const int kind = std::uniform_int_distribution<int>(0, 6)(rng_);
    const OrderId unknown = (OrderId{1} << 48) + next_id_++;
    switch (m.empty() ? 0 : kind) {
      case 0: return {EventType::Delete, Side::Buy, 7, 0, unknown, 0, 0, 0};
      case 1: return {EventType::Execute, Side::Buy, 7, 0, unknown, 0, qty(), 0};
      case 2: return {EventType::Cancel, Side::Buy, 7, 0, unknown, 0, qty(), 0};
      case 3: return replace(unknown, next_id_++, qty(), price());
      case 4: return add(m.pick(rng_), side(), qty(), price());
      case 5: return replace(m.pick(rng_), m.pick(rng_), qty(), price());
      default: return percent() < 50 ? add(next_id_++, side(), 0, price()) : replace(m.pick(rng_), next_id_++, 0, price());
    }
  }

  // Some refs are held back and added later, so an Add can carry a lower ref than orders already
  // resting (as with orders entered before the open).
  OrderId add_id() {
    if (!held_.empty() && percent() < 10) {
      const OrderId id = held_.back();
      held_.pop_back();
      ++late_adds_;
      return id;
    }
    if (percent() < 10) held_.push_back(next_id_++);
    return next_id_++;
  }

  static Event add(OrderId id, Side s, std::uint32_t q, Price p) { return {EventType::Add, s, 7, 0, id, 0, q, p}; }
  static Event replace(OrderId old_id, OrderId new_id, std::uint32_t q, Price p) {
    return {EventType::Replace, Side::Buy, 7, 0, old_id, new_id, q, p};
  }

  // Mostly partial, sometimes exact, occasionally more than resting (an excess reduction).
  std::uint32_t removal(std::uint32_t resting) {
    const int r = percent();
    if (r < 3) return resting + std::uniform_int_distribution<std::uint32_t>(1, 100)(rng_);
    if (r < 30 || resting == 1) return resting;
    return std::uniform_int_distribution<std::uint32_t>(1, resting - 1)(rng_);
  }

  int percent() { return std::uniform_int_distribution<int>(0, 99)(rng_); }
  Side side() { return percent() < 50 ? Side::Buy : Side::Sell; }
  std::uint32_t qty() { return std::uniform_int_distribution<std::uint32_t>(1, 1000)(rng_); }
  // One shared band for both sides, so levels interleave and the Book crosses.
  Price price() { return 100'0000 + 100 * std::uniform_int_distribution<Price>(0, kTicks - 1)(rng_); }

  std::mt19937_64 rng_;
  OrderId next_id_ = 1;
  std::vector<OrderId> held_;
  std::uint64_t late_adds_ = 0;
};

class BookProperty : public ::testing::TestWithParam<std::uint64_t> {};
}  // namespace

TEST_P(BookProperty, InvariantsAndModelAgreementHoldAfterEveryEvent) {
  Book book;
  Model model;
  Generator gen(GetParam());
  std::array<std::uint64_t, 6> types{};
  std::size_t peak_live = 0;

  for (int step = 0; step < kEventsPerSeed; ++step) {
    const Event ev = gen.next(model);
    ++types[static_cast<std::size_t>(ev.type)];
    book.apply(ev);
    model.apply(ev);
    peak_live = std::max(peak_live, model.size());

    ASSERT_NO_THROW(book.check_invariants()) << "step " << step;
    ASSERT_TRUE(same_snapshot(book.snapshot(kDepth), model.snapshot())) << "step " << step;
    ASSERT_TRUE(same_stats(book.stats(), model.stats)) << "step " << step;
    for (const LevelKey& key : model.touched) {
      ASSERT_EQ(book.fifo(key.first, key.second), model.fifo(key)) << "step " << step << " price " << key.second;
    }
  }

  // Guard against a vacuous run: every EventType and every counter must be exercised.
  for (std::size_t t = 0; t < types.size(); ++t) EXPECT_GT(types[t], 500u) << "EventType " << t;
  const BookStats& s = book.stats();
  EXPECT_EQ(s.events, static_cast<std::uint64_t>(kEventsPerSeed));
  EXPECT_GT(s.unknown_order_refs, 0u);
  EXPECT_GT(s.duplicate_order_refs, 0u);
  EXPECT_GT(s.zero_qty_adds, 0u);
  EXPECT_GT(s.excess_reductions, 0u);
  EXPECT_GT(s.exec_not_at_front, 0u);
  EXPECT_GT(s.exec_with_price_not_at_front, 0u);
  EXPECT_GT(gen.late_adds(), 50u);
  EXPECT_GT(peak_live, 20u);
}

INSTANTIATE_TEST_SUITE_P(Seeds, BookProperty, ::testing::Range<std::uint64_t>(1, 21));
