#include "4DPluginAPI.h"
#include "compact_lang_det.h"
#include "lang_script.h"
#include <string>
#include <vector>
#include <cstring>

static void doCLD2(PA_PluginParameters params);

#if defined(_WIN32)
#define PLUGIN_EXPORT extern "C" __declspec(dllexport)
#else
#define PLUGIN_EXPORT extern "C" __attribute__((visibility("default")))
#endif

PLUGIN_EXPORT
void PluginMain(PA_long32 selector, PA_PluginParameters params) {
    switch (PA_GetCurrentProcessNumber()) {
        case kInitPlugin:
        case kDeinitPlugin:
            break;
        default:
            switch (selector) {
                case 1: doCLD2(params); break;
            }
    }
}

static void doCLD2(PA_PluginParameters params) {
    PA_Unistring* ustr = PA_GetStringParameter(params, 1);
    if (!ustr) return;

    PA_Unichar* uChars = PA_GetUnistring(ustr);
    PA_long32 uLen = PA_GetUnistringLength(ustr);
    if (!uChars || uLen == 0) {
        PA_ReturnObject(params, PA_CreateObject());
        return;
    }

    // Convert UTF-16 to UTF-8
    PA_long32 utf8BufSize = uLen * 4 + 1;
    std::vector<char> utf8(utf8BufSize, 0);
    PA_ConvertCharsetToCharset(
        (char*)uChars, uLen * (PA_long32)sizeof(PA_Unichar),
        eVTC_UTF_16,
        utf8.data(), utf8BufSize,
        eVTC_UTF_8);

    int text_len = (int)strlen(utf8.data());

    CLD2::Language language3[3];
    int percent3[3];
    int text_bytes;
    bool is_reliable;

    CLD2::Language lang = CLD2::DetectLanguageSummary(
        utf8.data(), text_len, true,
        language3, percent3, &text_bytes, &is_reliable);

    // Build JSON
    std::string json = "{";
    json += "\"language\":\"" + std::string(CLD2::LanguageCode(lang)) + "\",";
    json += "\"languageName\":\"" + std::string(CLD2::LanguageName(lang)) + "\",";
    json += "\"reliable\":" + std::string(is_reliable ? "true" : "false") + ",";
    json += "\"textBytes\":" + std::to_string(text_bytes) + ",";
    json += "\"languages\":[";
    for (int i = 0; i < 3; i++) {
        if (i > 0) json += ",";
        json += "{\"code\":\"" + std::string(CLD2::LanguageCode(language3[i])) + "\",";
        json += "\"name\":\"" + std::string(CLD2::LanguageName(language3[i])) + "\",";
        json += "\"percent\":" + std::to_string(percent3[i]) + "}";
    }
    json += "]}";

    // Convert JSON to UTF-16 for PA_JsonParse
    PA_long32 json16BufSize = ((PA_long32)json.size() + 1) * (PA_long32)sizeof(PA_Unichar);
    std::vector<char> json16buf(json16BufSize, 0);
    PA_ConvertCharsetToCharset(
        (char*)json.c_str(), (PA_long32)json.size(),
        eVTC_UTF_8,
        json16buf.data(), json16BufSize,
        eVTC_UTF_16);

    PA_Unistring jsonUstr = PA_CreateUnistring((PA_Unichar*)json16buf.data());

    // Bypass PA_JsonParse (SDK bug: params not initialized for eVK_Object path)
    PA_Variable cmdParams[2];
    memset(cmdParams, 0, sizeof(cmdParams));
    PA_SetStringVariable(&cmdParams[0], &jsonUstr);
    PA_SetLongintVariable(&cmdParams[1], eVK_Object);
    PA_Variable result = PA_ExecuteCommandByID(1218, cmdParams, 2); // JSON Parse

    PA_ReturnObject(params, PA_GetObjectVariable(result));
}
