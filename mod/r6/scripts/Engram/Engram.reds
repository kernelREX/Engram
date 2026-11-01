// Engram, the redscript half.
//
// redscript owns the menus and nothing else. It cannot open a file or a socket, so every
// line here that does real work is a call into the native plugin in red4ext/plugins/Engram.
// If that plugin is missing, these calls do not resolve and the game refuses to compile the
// scripts, which is why IsAvailable exists: callers check it before offering the buttons.

module Engram

// The native class the plugin registers. The signatures have to match what
// native/src/Main.cpp registers in PostRegisterTypes, exactly, or the game will not load.
public native class EngramNative extends IScriptable {
    // The plugin's own version, for checking it against the standalone tool's.
    public static native func Version() -> String

    // Where Cyberpunk keeps its saves on this machine, asked of Windows rather than guessed.
    public static native func SaveFolder() -> String

    // Save folder names, newest first.
    public static native func SaveNames() -> array<String>
}

public class Engram {
    public static func Version() -> String {
        return EngramNative.Version();
    }

    // Whether the native half is present and answering. Everything the player can press is
    // behind this, so a half installed mod shows nothing rather than failing mid press.
    public static func IsAvailable() -> Bool {
        return StrLen(EngramNative.Version()) > 0;
    }

    public static func SaveFolder() -> String {
        return EngramNative.SaveFolder();
    }

    public static func SaveNames() -> array<String> {
        return EngramNative.SaveNames();
    }
}
