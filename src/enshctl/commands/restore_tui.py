"""Interactive restore picker backed by Textual."""

import logging
from typing import TYPE_CHECKING, ClassVar, override

from enshctl.restore import RestoreError
from enshctl.utils import human_size

if TYPE_CHECKING:
    from collections.abc import Sequence

    from enshctl.backup.catalog import BackupInfo

logger = logging.getLogger(__name__)


def select_backup(backups: Sequence[BackupInfo]) -> BackupInfo | None:
    """Run the interactive picker and return the chosen Backup, if any."""
    try:
        from textual.app import App, ComposeResult
        from textual.binding import Binding, BindingType
        from textual.widgets import Footer, Header, ListItem, ListView, Static
    except ImportError:
        logger.exception("Interactive restore requires Textual. Use --file or --when instead.")
        msg = "Interactive restore requires Textual. Use --file or --when instead."
        raise RestoreError(msg) from None

    class RestoreApp(App[None]):
        BINDINGS: ClassVar[list[BindingType]] = [
            Binding("q", "quit", "Quit"),
            Binding("escape", "quit", "Quit"),
        ]

        def __init__(self) -> None:
            super().__init__()
            self._backups = backups
            self.selected: BackupInfo | None = None

        @override
        def compose(self) -> ComposeResult:
            yield Header()
            yield Static("Select a backup to restore (q to quit)")
            yield ListView(*[ListItem(Static(f"{bi.path.name} ({human_size(bi.size)})")) for bi in self._backups])
            yield Footer()

        def on_list_view_selected(self, event: ListView.Selected) -> None:
            list_view = self.query_one(ListView)
            for idx, item in enumerate(list_view.children):
                if item is event.item:
                    self.selected = self._backups[idx]
                    self.exit()
                    return

        @override
        async def action_quit(self) -> None:
            self.exit()

    app = RestoreApp()
    app.run()
    return app.selected
