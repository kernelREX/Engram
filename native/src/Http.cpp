#include "Http.hpp"

#include <stdexcept>

#include <windows.h>

#include <winhttp.h>

#include "Code.hpp"
#include "Crypto.hpp"

#pragma comment(lib, "winhttp.lib")

namespace
{
constexpr DWORD kTimeoutMs = 300000;
constexpr size_t kMaxDownload = 256ull * 1024 * 1024;

std::wstring Widen(const std::string& aText)
{
    if (aText.empty())
    {
        return {};
    }
    const int needed =
        MultiByteToWideChar(CP_UTF8, 0, aText.c_str(), static_cast<int>(aText.size()), nullptr, 0);
    std::wstring out(static_cast<size_t>(needed), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, aText.c_str(), static_cast<int>(aText.size()), out.data(),
                        needed);
    return out;
}

std::string Narrow(const std::wstring& aText)
{
    if (aText.empty())
    {
        return {};
    }
    const int needed = WideCharToMultiByte(CP_UTF8, 0, aText.c_str(),
                                           static_cast<int>(aText.size()), nullptr, 0, nullptr,
                                           nullptr);
    std::string out(static_cast<size_t>(needed), '\0');
    WideCharToMultiByte(CP_UTF8, 0, aText.c_str(), static_cast<int>(aText.size()), out.data(),
                        needed, nullptr, nullptr);
    return out;
}

struct Handle
{
    HINTERNET value = nullptr;
    ~Handle()
    {
        if (value)
        {
            WinHttpCloseHandle(value);
        }
    }
    Handle() = default;
    explicit Handle(HINTERNET aValue) : value(aValue) {}
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
    operator bool() const { return value != nullptr; }
};

struct Parts
{
    std::wstring host;
    std::wstring path;
    INTERNET_PORT port = 0;
    bool secure = false;
};

Parts Split(const std::string& aUrl)
{
    const std::wstring url = Widen(aUrl);
    URL_COMPONENTS components{};
    components.dwStructSize = sizeof(components);

    wchar_t host[256] = {};
    wchar_t path[2048] = {};
    components.lpszHostName = host;
    components.dwHostNameLength = static_cast<DWORD>(std::size(host));
    components.lpszUrlPath = path;
    components.dwUrlPathLength = static_cast<DWORD>(std::size(path));

    if (!WinHttpCrackUrl(url.c_str(), static_cast<DWORD>(url.size()), 0, &components))
    {
        throw std::runtime_error("could not read the address " + aUrl);
    }

    Parts parts;
    parts.host = host;
    parts.path = path[0] ? path : L"/";
    parts.port = components.nPort;
    parts.secure = components.nScheme == INTERNET_SCHEME_HTTPS;
    return parts;
}

std::string HostOf(const std::string& aUrl)
{
    try
    {
        return Narrow(Split(aUrl).host);
    }
    catch (const std::exception&)
    {
        return aUrl;
    }
}

std::string ExplainStatus(const std::string& aUrl, DWORD aStatus)
{
    const std::string host = HostOf(aUrl);
    switch (aStatus)
    {
    case 404:
        return host +
               " has no file at that address. Codes expire after 72 hours, so this one has "
               "most likely run out, or the middle of the code was misheard.";
    case 403:
    case 418:
        return host + " refused the request. The host may be blocking automated uploads. "
                      "Try again later, or use the Engram tool outside the game.";
    case 429:
        return host +
               " is rate limiting this connection. Wait a few minutes rather than retrying.";
    case 413:
        return host + " says the file is too large";
    default:
        break;
    }
    if (aStatus >= 500 && aStatus < 600)
    {
        return host + " is having trouble right now. Try the other host.";
    }
    return host + " answered " + std::to_string(aStatus);
}

// One request, start to finish. No retry loop: these are volunteer run services doing us a
// favour, and hammering them is how a free host stops being free.
engram::Bytes Request(const std::string& aUrl, const char* aMethod,
                      const std::wstring& aHeaders, const engram::Bytes& aBody,
                      std::string* aResponseHeaderOut, const std::wstring& aWantedHeader)
{
    const Parts parts = Split(aUrl);

    Handle session(WinHttpOpen(Widen(engram::UserAgent()).c_str(),
                               WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY, WINHTTP_NO_PROXY_NAME,
                               WINHTTP_NO_PROXY_BYPASS, 0));
    if (!session)
    {
        throw std::runtime_error("could not start a network session");
    }
    WinHttpSetTimeouts(session.value, 30000, 30000, kTimeoutMs, kTimeoutMs);

    Handle connection(WinHttpConnect(session.value, parts.host.c_str(), parts.port, 0));
    if (!connection)
    {
        throw std::runtime_error("could not reach " + Narrow(parts.host));
    }

    Handle request(WinHttpOpenRequest(connection.value, Widen(aMethod).c_str(),
                                      parts.path.c_str(), nullptr, WINHTTP_NO_REFERER,
                                      WINHTTP_DEFAULT_ACCEPT_TYPES,
                                      parts.secure ? WINHTTP_FLAG_SECURE : 0));
    if (!request)
    {
        throw std::runtime_error("could not prepare a request to " + Narrow(parts.host));
    }

    const BOOL sent = WinHttpSendRequest(
        request.value, aHeaders.empty() ? WINHTTP_NO_ADDITIONAL_HEADERS : aHeaders.c_str(),
        aHeaders.empty() ? 0 : static_cast<DWORD>(-1),
        aBody.empty() ? WINHTTP_NO_REQUEST_DATA : const_cast<uint8_t*>(aBody.data()),
        static_cast<DWORD>(aBody.size()), static_cast<DWORD>(aBody.size()), 0);
    if (!sent || !WinHttpReceiveResponse(request.value, nullptr))
    {
        throw std::runtime_error("could not reach " + Narrow(parts.host) +
                                 ". Check the connection.");
    }

    DWORD status = 0;
    DWORD statusSize = sizeof(status);
    WinHttpQueryHeaders(request.value,
                        WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER, nullptr,
                        &status, &statusSize, nullptr);
    if (status < 200 || status >= 300)
    {
        throw std::runtime_error(ExplainStatus(aUrl, status));
    }

    if (aResponseHeaderOut && !aWantedHeader.empty())
    {
        DWORD size = 0;
        WinHttpQueryHeaders(request.value, WINHTTP_QUERY_CUSTOM, aWantedHeader.c_str(),
                            WINHTTP_NO_OUTPUT_BUFFER, &size, WINHTTP_NO_HEADER_INDEX);
        if (size > 0 && GetLastError() == ERROR_INSUFFICIENT_BUFFER)
        {
            std::wstring value(size / sizeof(wchar_t), L'\0');
            if (WinHttpQueryHeaders(request.value, WINHTTP_QUERY_CUSTOM, aWantedHeader.c_str(),
                                    value.data(), &size, WINHTTP_NO_HEADER_INDEX))
            {
                while (!value.empty() && value.back() == L'\0')
                {
                    value.pop_back();
                }
                *aResponseHeaderOut = Narrow(value);
            }
        }
    }

    engram::Bytes out;
    for (;;)
    {
        DWORD available = 0;
        if (!WinHttpQueryDataAvailable(request.value, &available) || available == 0)
        {
            break;
        }
        const size_t before = out.size();
        if (before + available > kMaxDownload)
        {
            throw std::runtime_error(
                "the download is far larger than any save, so it was stopped");
        }
        out.resize(before + available);
        DWORD read = 0;
        if (!WinHttpReadData(request.value, out.data() + before, available, &read))
        {
            throw std::runtime_error("the download stopped part way through");
        }
        out.resize(before + read);
        if (read == 0)
        {
            break;
        }
    }
    return out;
}

std::string Trim(const std::string& aText)
{
    const auto first = aText.find_first_not_of(" \t\r\n");
    if (first == std::string::npos)
    {
        return {};
    }
    const auto last = aText.find_last_not_of(" \t\r\n");
    return aText.substr(first, last - first + 1);
}
} // namespace

namespace engram
{
std::string UserAgent()
{
    // Says what we are and where to find us, so a host operator can get in touch rather
    // than guess. Several hosts refuse a default library user agent outright.
    return std::string("Engram/") + kEngramVersion + " (+https://github.com/tfthushaar/Engram)";
}

UploadResult Upload(const Host& aHost, const Bytes& aContent, int aHours)
{
    if (aContent.size() > aHost.maxBytes)
    {
        throw std::runtime_error(aHost.label + " takes files up to " +
                                 std::to_string(aHost.maxBytes / (1024 * 1024)) +
                                 " MB and this one is bigger");
    }

    // Built in memory, because a save is only a few megabytes.
    const std::string boundary = "----EngramBoundary" + [] {
        static const char* digits = "0123456789abcdef";
        std::string out;
        for (const auto byte : RandomBytes(16))
        {
            out.push_back(digits[byte >> 4]);
            out.push_back(digits[byte & 0x0F]);
        }
        return out;
    }();

    std::vector<std::pair<std::string, std::string>> fields;
    std::string fileField = "fileToUpload";
    if (aHost.key == "litterbox")
    {
        fields.push_back({"reqtype", "fileupload"});
        fields.push_back({"time", aHost.ExpirySpelling(aHours)});
    }
    else
    {
        fileField = "file";
        fields.push_back({"expires", aHost.ExpirySpelling(aHours)});
    }

    std::string head;
    for (const auto& [name, value] : fields)
    {
        head += "--" + boundary + "\r\nContent-Disposition: form-data; name=\"" + name +
                "\"\r\n\r\n" + value + "\r\n";
    }
    head += "--" + boundary + "\r\nContent-Disposition: form-data; name=\"" + fileField +
            "\"; filename=\"" + aHost.uploadFilename +
            "\"\r\nContent-Type: application/octet-stream\r\n\r\n";
    const std::string tail = "\r\n--" + boundary + "--\r\n";

    Bytes body(head.begin(), head.end());
    body.insert(body.end(), aContent.begin(), aContent.end());
    body.insert(body.end(), tail.begin(), tail.end());

    const std::wstring headers =
        L"Content-Type: multipart/form-data; boundary=" + Widen(boundary) + L"\r\n";

    std::string token;
    const Bytes answer =
        Request(aHost.uploadUrl, "POST", headers, body, &token, L"X-Token");
    const std::string url = Trim(std::string(answer.begin(), answer.end()));

    if (url.rfind("http", 0) != 0)
    {
        throw std::runtime_error(aHost.label +
                                 " answered with something that is not a link. The host may "
                                 "be refusing uploads right now.");
    }

    // A host quietly changing its URL scheme fails here, at the moment of sharing, rather
    // than handing somebody a code that does not resolve three days later.
    const std::string id = aHost.IdFromUrl(url);
    if (id.empty())
    {
        throw std::runtime_error(aHost.label +
                                 " answered with an address Engram does not recognise. The "
                                 "host has changed.");
    }

    return UploadResult{id, url, token};
}

Bytes Download(const Host& aHost, const std::string& aFileId)
{
    return Request(aHost.UrlFor(aFileId), "GET", {}, {}, nullptr, {});
}
} // namespace engram
