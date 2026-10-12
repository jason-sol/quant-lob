#include "qlob/book.hpp"

#include <cassert>
#include <stdexcept>
#include <string>

namespace qlob {
namespace {
template <class Levels>
std::vector<LevelView> top(const Levels& levels, std::size_t depth) {
  std::vector<LevelView> out(depth);
  std::size_t i = 0;
  for (auto it = levels.begin(); it != levels.end() && i < depth; ++it, ++i) {
    out[i] = {it->first, it->second.total};
  }
  return out;
}

template <class Levels>
using FifoIt = typename decltype(Levels::mapped_type::fifo)::iterator;

template <class Levels>
void erase_from_level(Levels& levels, Price price, FifoIt<Levels> it) {
  auto lvl = levels.find(price);
  assert(lvl != levels.end());
  lvl->second.total -= it->qty;
  lvl->second.fifo.erase(it);
  if (lvl->second.fifo.empty()) levels.erase(lvl);
}

[[noreturn]] void fail(const std::string& what) { throw std::logic_error("Book invariant: " + what); }
}  // namespace

void Book::apply(const Event& ev) {
  ++stats_.events;
  switch (ev.type) {
    case EventType::Add:
      add(ev.order_id, ev.side, ev.qty, ev.price);
      break;
    case EventType::Delete:
      remove(ev.order_id);
      break;
    default:
      break;
  }
}

void Book::add(OrderId id, Side side, std::uint32_t qty, Price price) {
  if (orders_.contains(id)) {
    ++stats_.duplicate_order_refs;
    return;
  }
  if (qty == 0) {
    ++stats_.zero_qty_adds;
    return;
  }
  Level& lvl = side == Side::Buy ? bids_[price] : asks_[price];
  lvl.total += qty;
  auto it = lvl.fifo.insert(lvl.fifo.end(), Resting{id, qty});
  orders_.emplace(id, Locator{side, price, it});
}

void Book::remove(OrderId id) {
  auto found = orders_.find(id);
  if (found == orders_.end()) {
    ++stats_.unknown_order_refs;
    return;
  }
  const Locator& loc = found->second;
  if (loc.side == Side::Buy) {
    erase_from_level(bids_, loc.price, loc.it);
  } else {
    erase_from_level(asks_, loc.price, loc.it);
  }
  orders_.erase(found);
}

Snapshot Book::snapshot(std::size_t depth) const { return {top(bids_, depth), top(asks_, depth)}; }

bool Book::crossed() const {
  return !bids_.empty() && !asks_.empty() && bids_.begin()->first >= asks_.begin()->first;
}

void Book::check_invariants() const {
  std::size_t resting = 0;
  auto check_side = [&](const auto& levels, Side side) {
    for (const auto& [price, lvl] : levels) {
      if (lvl.fifo.empty() || lvl.total == 0) fail("empty Price level at " + std::to_string(price));
      std::uint64_t sum = 0;
      for (const Resting& r : lvl.fifo) {
        sum += r.qty;
        ++resting;
        auto found = orders_.find(r.id);
        if (found == orders_.end()) fail("resting order " + std::to_string(r.id) + " has no locator");
        const Locator& loc = found->second;
        // Together with the count check below, this makes locators and FIFO entries a bijection.
        if (loc.side != side || loc.price != price || &*loc.it != &r) {
          fail("locator for order " + std::to_string(r.id) + " does not point at its FIFO entry");
        }
      }
      if (sum != lvl.total) fail("Price level total mismatch at " + std::to_string(price));
    }
  };
  check_side(bids_, Side::Buy);
  check_side(asks_, Side::Sell);
  if (resting != orders_.size()) fail("locator count != resting order count");
}
}  // namespace qlob
