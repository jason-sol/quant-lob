#pragma once
#include <cstddef>
#include <cstdint>
#include <functional>
#include <list>
#include <map>
#include <unordered_map>
#include <vector>

#include "qlob/event.hpp"

namespace qlob {
struct LevelView { Price price = 0; std::uint64_t qty = 0; };
struct Snapshot { std::vector<LevelView> bids, asks; };
struct BookStats {
  std::uint64_t events = 0, unknown_order_refs = 0, duplicate_order_refs = 0, overfills = 0, zero_qty_adds = 0;
};

class Book {
 public:
  void apply(const Event& ev);
  Snapshot snapshot(std::size_t depth) const;
  bool crossed() const;
  void check_invariants() const;  // throws std::logic_error
  const BookStats& stats() const { return stats_; }

 private:
  struct Resting { OrderId id; std::uint32_t qty; };
  struct Level { std::uint64_t total = 0; std::list<Resting> fifo; };
  struct Locator { Side side; Price price; std::list<Resting>::iterator it; };

  void add(OrderId id, Side side, std::uint32_t qty, Price price);
  void remove(OrderId id);

  std::map<Price, Level, std::greater<>> bids_;
  std::map<Price, Level> asks_;
  std::unordered_map<OrderId, Locator> orders_;
  BookStats stats_;
};
}  // namespace qlob
