include(GoogleTest)
add_executable(qlob_tests smoke_test.cpp)
target_link_libraries(qlob_tests PRIVATE qlob GTest::gtest_main)
gtest_discover_tests(qlob_tests)
