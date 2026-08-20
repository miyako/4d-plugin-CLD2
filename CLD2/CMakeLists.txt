cmake_minimum_required(VERSION 3.15)
project(CLD2 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 11)
set(CMAKE_C_VISIBILITY_PRESET default)
set(CMAKE_CXX_VISIBILITY_PRESET default)

if(APPLE)
    set(CMAKE_OSX_ARCHITECTURES "x86_64;arm64")
endif()

set(SDK_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../4D-Plugin-SDK/4D Plugin API")
set(CLD2_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../cld2-src")

set(CLD2_SOURCES
    ${CLD2_DIR}/internal/cldutil.cc
    ${CLD2_DIR}/internal/cldutil_shared.cc
    ${CLD2_DIR}/internal/compact_lang_det.cc
    ${CLD2_DIR}/internal/compact_lang_det_hint_code.cc
    ${CLD2_DIR}/internal/compact_lang_det_impl.cc
    ${CLD2_DIR}/internal/debug.cc
    ${CLD2_DIR}/internal/fixunicodevalue.cc
    ${CLD2_DIR}/internal/generated_entities.cc
    ${CLD2_DIR}/internal/generated_language.cc
    ${CLD2_DIR}/internal/generated_ulscript.cc
    ${CLD2_DIR}/internal/getonescriptspan.cc
    ${CLD2_DIR}/internal/lang_script.cc
    ${CLD2_DIR}/internal/offsetmap.cc
    ${CLD2_DIR}/internal/scoreonescriptspan.cc
    ${CLD2_DIR}/internal/tote.cc
    ${CLD2_DIR}/internal/utf8statetable.cc
    ${CLD2_DIR}/internal/cld_generated_cjk_uni_prop_80.cc
    ${CLD2_DIR}/internal/cld2_generated_cjk_compatible.cc
    ${CLD2_DIR}/internal/cld_generated_cjk_delta_bi_32.cc
    ${CLD2_DIR}/internal/generated_distinct_bi_0.cc
    ${CLD2_DIR}/internal/cld2_generated_quad0122.cc
    ${CLD2_DIR}/internal/cld2_generated_deltaocta0122.cc
    ${CLD2_DIR}/internal/cld2_generated_distinctocta0122.cc
    ${CLD2_DIR}/internal/cld_generated_score_quad_octa_0122.cc
)

add_library(CLD2 MODULE
    CLD2-4dplugin.cpp
    "${SDK_DIR}/4DPluginAPI.c"
    ${CLD2_SOURCES}
)

target_include_directories(CLD2 PRIVATE
    "${SDK_DIR}"
    "${CLD2_DIR}/public"
    "${CLD2_DIR}/internal"
)

if(APPLE)
    set_target_properties(CLD2 PROPERTIES
        BUNDLE TRUE
        BUNDLE_EXTENSION "bundle"
        PREFIX ""
        MACOSX_BUNDLE_INFO_PLIST "${CMAKE_CURRENT_SOURCE_DIR}/Info.plist"
    )

    set(PLUGIN_OUTPUT "${CMAKE_CURRENT_SOURCE_DIR}/CLD2-test/Plugins/CLD2.bundle")
    add_custom_command(TARGET CLD2 POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E remove_directory "${PLUGIN_OUTPUT}"
        COMMAND ${CMAKE_COMMAND} -E copy_directory "$<TARGET_BUNDLE_DIR:CLD2>" "${PLUGIN_OUTPUT}"
        COMMAND ${CMAKE_COMMAND} -E make_directory "${PLUGIN_OUTPUT}/Contents/Resources"
        COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/manifest.json" "${PLUGIN_OUTPUT}/Contents/Resources/manifest.json"
    )

    target_compile_options(CLD2 PRIVATE
        -Wno-c++11-narrowing
        -Wno-int-conversion
        -Wno-deprecated-declarations
        -Wno-writable-strings
        -Wno-tautological-undefined-compare
    )

    find_library(COREGRAPHICS_FRAMEWORK CoreGraphics)
    find_library(COREFOUNDATION_FRAMEWORK CoreFoundation)
    find_library(COCOA_FRAMEWORK Cocoa)
    target_link_libraries(CLD2 PRIVATE
        ${COREGRAPHICS_FRAMEWORK}
        ${COREFOUNDATION_FRAMEWORK}
        ${COCOA_FRAMEWORK}
    )
elseif(WIN32)
    set_target_properties(CLD2 PROPERTIES
        PREFIX ""
        SUFFIX ".4DX"
    )

    set(PLUGIN_OUTPUT_DIR "${CMAKE_CURRENT_SOURCE_DIR}/CLD2-test/Plugins")
    add_custom_command(TARGET CLD2 POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E make_directory "${PLUGIN_OUTPUT_DIR}"
        COMMAND ${CMAKE_COMMAND} -E copy "$<TARGET_FILE:CLD2>" "${PLUGIN_OUTPUT_DIR}/CLD2.4DX"
        COMMAND ${CMAKE_COMMAND} -E make_directory "${PLUGIN_OUTPUT_DIR}/CLD2.4DX.Resources"
        COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/manifest.json" "${PLUGIN_OUTPUT_DIR}/CLD2.4DX.Resources/manifest.json"
    )

    target_compile_options(CLD2 PRIVATE
        /W3 /wd4267 /wd4244 /wd4305
    )
endif()
