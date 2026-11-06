#pragma once

#include <filesystem>
#include <string>
#include <vector>

namespace engram
{
// One mod, as much as can be known about it from the outside. Mirrors engram/mods.py.
struct ModEntry
{
    std::string name;
    std::string kind;     // redscript, red4ext, archive, redmod, cet, tweak
    std::string version;  // empty when the mod publishes none
    bool writesPersistentState = false;
    bool persistentKnown = false;
    bool declared = false;
    bool extendsRecords = false;

    std::string Key() const;
    std::string Label() const;
};

struct ModSet
{
    std::vector<ModEntry> entries;
    bool phantomLiberty = false;

    bool HasFramework(const std::string& aNormalisedName) const;
    std::vector<ModEntry> OfKind(const std::string& aKind) const;
};

// Fingerprint an install.
ModSet ScanMods(const std::filesystem::path& aGameDir);

ModSet ModsFromJson(const std::string& aJson);
std::string ModsToJson(const ModSet& aMods);

// Fold a mod name so two installs agree on it. Folder names arrive with the version baked
// in often enough that ignoring it would report one mod as both missing and extra.
std::string NormaliseName(const std::string& aName);

// How strongly the receiver should be told about something.
enum class Severity
{
    Note = 0,
    Warn = 1,
    Block = 2,
};

struct Finding
{
    Severity severity = Severity::Note;
    std::string code;
    std::string summary;
    std::string detail;
    std::vector<std::string> items;
};

struct CheckReport
{
    std::vector<Finding> findings;

    bool Blocked() const;
    int CountOf(Severity aSeverity) const;
    std::string Summarise() const;

    // Flattened for the menu, worst first: each line is "severity\tsummary\tdetail\titems".
    std::vector<std::string> Lines() const;
};

// Everything worth saying about installing this save here.
//
// `aInsideGame` is set by the mod, which runs in Cyberpunk's own process. There the game
// being open is not a reason to refuse anything: it is simply where we are. Asking whether
// Cyberpunk is running from inside Cyberpunk always says yes, so the mod passes false for
// `aGameRunning` and true for this, and gets the note about the load list instead of a
// block it could never satisfy.
CheckReport BuildReport(const std::string& aSaveJson, const ModSet& aSender,
                        const ModSet& aReceiver, int aReceiverGameVersion,
                        bool aGameRunning, bool aSteamRunning, bool aInsideGame = false);

// The alert both sides get: this save was made with mods, and here they are. Sent to the
// receiver inside the manifest and shown to the sender before they read the code out, so
// neither of them is surprised by what travelled.
Finding ModsOnThisSave(const ModSet& aMods);
} // namespace engram
