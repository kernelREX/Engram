// A probe, for step one of the mod: prove the pipeline before building anything on it.
//
// It writes what the native half reports into the redscript log. Seeing those lines in
// r6/logs/redscript_rCURRENT.log means the DLL loaded, its class reached the RTTI system,
// redscript resolved the natives, and strings and arrays survived the boundary in both
// directions. Those are the four things every later piece depends on.
//
// Delete this file once the menus exist. It is scaffolding, not a feature.

module Engram.Probe

import Engram.*

public class EngramProbe extends ScriptableSystem {
    private func OnAttach() -> Void {
        if !Engram.IsAvailable() {
            LogChannel(n"Engram", "the native plugin is not answering");
            return;
        }

        LogChannel(n"Engram", s"version \(Engram.Version())");
        LogChannel(n"Engram", s"save folder \(Engram.SaveFolder())");

        let names = Engram.SaveNames();
        LogChannel(n"Engram", s"\(ArraySize(names)) save(s) found");

        let shown = Min(ArraySize(names), 5);
        let i = 0;
        while i < shown {
            LogChannel(n"Engram", s"  \(names[i])");
            i += 1;
        }
    }
}
