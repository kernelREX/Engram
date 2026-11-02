// The Engram entry in the main menu and the pause menu.
//
// Two things here are not obvious and both caused real failures.
//
// The entry goes directly after the game's own Mods entry, never earlier. The main menu
// hardcodes the index of its mod.io button: singleplayerMenu.script:1153 reads
//
//     m_modioButton = inkCompoundRef.GetWidgetByIndex(m_menuList, m_savesCount > 0 ? 4 : 3)
//
// so inserting anything above that index hands the game's mod.io wiring to the wrong
// button, and the player gets asked to sign in to mod.io by a button that has nothing to
// do with it. Adding after Mods leaves every index the game assumes exactly where it was.
//
// The click is handled on the controller, not the scenario. HandleMenuItemActivate sends a
// menu item's event through m_menuEventDispatcher.SpawnEvent, which routes to the
// MenuScenario, and a scenario is not an inkGameController so it has no widget tree to put
// a popup in. Wrapping HandleMenuItemActivate catches the press on the controller itself,
// which is the thing the popup needs.

module Engram.MainMenu

import Engram.Popup.*

@addField(gameuiMenuItemListGameController)
private let m_engramAdded: Bool;

@wrapMethod(gameuiMenuItemListGameController)
protected func AddMenuItem(const label: script_ref<String>, spawnEvent: CName) {
  wrappedMethod(label, spawnEvent);

  if !Engram.IsAvailable() || this.m_engramAdded {
    return;
  };

  // Directly after the Mods entry, in both the main menu and the pause menu.
  if Equals(spawnEvent, n"OnSwitchToModioMenu") {
    wrappedMethod("Engram", n"OnOpenEngram");
    this.m_engramAdded = true;
  };
}

// If the Mods entry never appears, which happens when another mod hides it or rebuilds the
// list, put ours at the end rather than nowhere. The end is always safe: everything the
// game indexes sits above it.
@addMethod(gameuiMenuItemListGameController)
protected func AddEngramIfMissing() {
  if !this.m_engramAdded && Engram.IsAvailable() {
    this.AddMenuItem("Engram", n"OnOpenEngram");
    this.m_engramAdded = true;
    this.m_menuListController.Refresh();
  };
}

@wrapMethod(SingleplayerMenuGameController)
private func PopulateMenuItemList() {
  this.m_engramAdded = false;
  wrappedMethod();
  this.AddEngramIfMissing();
}

@wrapMethod(PauseMenuGameController)
private func PopulateMenuItemList() {
  this.m_engramAdded = false;
  wrappedMethod();
  this.AddEngramIfMissing();
}

// Catch the press here rather than letting it go to the scenario, which cannot host a
// popup. Everything else carries on to the game's own handling untouched.
@wrapMethod(gameuiMenuItemListGameController)
protected func HandleMenuItemActivate(data: ref<PauseMenuListItemData>) -> Bool {
  if Equals(data.eventName, n"OnOpenEngram") {
    EngramPopup.Show(this);
    return true;
  };
  return wrappedMethod(data);
}
