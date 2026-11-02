// The Engram entry in the main menu and the pause menu.
//
// This follows the same approach Mod Settings uses, for the same reason its author gives:
// the entry is added next to one of the game's own entries rather than by replacing
// PopulateMenuItemList, so entries a patch adds survive, and the indices the game hardcodes
// stay where they are. The 2.5 main menu attaches its mod.io tooltip to whatever item sits
// in the Mods slot, which is exactly the kind of thing that breaks when you rebuild the
// list yourself.

module Engram.MainMenu

import Engram.Popup.*

@addField(gameuiMenuItemListGameController)
private let m_engramAdded: Bool;

@wrapMethod(gameuiMenuItemListGameController)
protected func AddMenuItem(const label: script_ref<String>, spawnEvent: CName) {
  wrappedMethod(label, spawnEvent);

  if !Engram.IsAvailable() {
    return;
  }

  // Right after Load Game, because that is what Engram is about.
  if Equals(spawnEvent, n"OnLoadGame") {
    wrappedMethod("Engram", n"OnOpenEngram");
    this.m_engramAdded = true;
  };
}

// If the Load Game entry never appears, which happens when another mod rebuilds the list,
// put ours at the end rather than nowhere.
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

// The entry is on the menu list controller, but the popup has to be opened by a controller
// that owns a widget tree to put it in, which is the menu game controller itself.
@addMethod(SingleplayerMenuGameController)
protected cb func OnOpenEngram() -> Bool {
  EngramPopup.Show(this);
}

@addMethod(PauseMenuGameController)
protected cb func OnOpenEngram() -> Bool {
  EngramPopup.Show(this);
}
