# Keyboard firmware notes

## QMK keymap changes

The keymap lives in `keymaps/<name>/keymap.c` as layers of keycode matrices.
Swapping Caps Lock for Escape-on-tap, Control-on-hold is one line:
`LCTL_T(KC_ESC)` in the Caps position. Keep a raw layer with plain keycodes
for troubleshooting.

## Flashing

`qmk compile -kb <board> -km <name>` builds the hex; put the board in
bootloader mode (usually the physical reset button double-tap) and
`qmk flash` picks it up. If the board enumerates but flashing hangs, try a
data-capable cable — charging cables are the usual culprit.

## Home row mods

Tap-hold timing is personal: start with `TAPPING_TERM 200` and lower it
until rolls stop misfiring. Enable `PERMISSIVE_HOLD` before blaming your
typing.
