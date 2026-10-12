#pragma once
#include <cstdint>

namespace qlob {
using Price = std::uint32_t;  // ITCH price, 4 implied decimals
using OrderId = std::uint64_t;
enum class Side : std::uint8_t { Buy, Sell };
enum class EventType : std::uint8_t { Add, Cancel, Delete, Execute, Replace, ExecuteWithPrice };

struct Event {
  EventType type;
  Side side;              // Add only; Replace takes the original's side in the Book
  std::uint16_t locate;
  std::uint64_t ts_ns;
  OrderId order_id;       // Replace: original id
  OrderId new_order_id;   // Replace only
  std::uint32_t qty;      // Add/Replace: shares; Cancel/Execute: shares removed
  Price price;            // Add/Replace
};
}  // namespace qlob
