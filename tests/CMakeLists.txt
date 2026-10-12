include(GoogleTest)
add_executable(qlob_tests smoke_test.cpp itch_test.cpp book_test.cpp replay_test.cpp)
target_link_libraries(qlob_tests PRIVATE qlob GTest::gtest_main)
target_compile_definitions(qlob_tests PRIVATE QLOB_REPLAY_PATH="$<TARGET_FILE:qlob_replay>")
add_dependencies(qlob_tests qlob_replay)
gtest_discover_tests(qlob_tests)

# Use-after-return fake stacks make these step-heavy loops over 10x slower under GCC ASan.
add_executable(qlob_property_tests book_property_test.cpp)
target_link_libraries(qlob_property_tests PRIVATE qlob GTest::gtest_main)
gtest_discover_tests(qlob_property_tests
  PROPERTIES ENVIRONMENT "ASAN_OPTIONS=detect_stack_use_after_return=0")
