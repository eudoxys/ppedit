"""@private Name of the editor shown in the browser page

Change `APP_NAME` to show another name wherever the page shows `ppedit`:
the window title, the top-bar title, tooltips, server status dialogs and
messages, and the About dialog heading. `APP_MARK` is the leading part of
the name drawn in the accent color in the top bar (`""` for none; it is
ignored when the name does not start with it).

The name only changes what the page shows. The package, the `ppedit`
command (shown by the restart dialog as the command to run), `localStorage`
keys, and the copyright, license and funding acknowledgment in the About
dialog are not changed by it; when `APP_NAME` is not `ppedit`, the About
dialog also says that the editor is based on ppedit.

Example:

    APP_NAME = "GridEdit"
    APP_MARK = "Grid"
"""

APP_NAME = "ppedit"
"""@private Name of the editor shown in the browser page"""

APP_MARK = "pp"
"""Leading part of `APP_NAME` drawn in the accent color in the top bar"""
