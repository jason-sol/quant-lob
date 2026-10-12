#include <gtest/gtest.h>
#include <type_traits>
#include "qlob/event.hpp"

TEST(Smoke, EventIsTriviallyCopyable) {
  static_assert(std::is_trivially_copyable_v<qlob::Event>);
}
