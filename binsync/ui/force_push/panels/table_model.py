import logging
import datetime
from typing import Dict, Set

from binsync.controller import BSController
from libbs.ui.qt_objects import (
    QAbstractItemView,
    QAbstractTableModel,
    QApplication,
    QHeaderView,
    Qt,
    QModelIndex,
    QSortFilterProxyModel,
    QColor,
    QFocusEvent,
    QKeyEvent,
    QLineEdit,
    QTableView,
    QFontDatabase,
    QCursor,
    Signal,
    Slot,
)

l = logging.getLogger(__name__)


class BinsyncTableModel(QAbstractTableModel):
    # Custom defined role for sorting/filtering (since we shouldn't sort hex numbers alphabetically)
    SortRole = Qt.UserRole + 1000
    FilterRole = Qt.UserRole + 1001

    # Color for most recently updated, the alpha value decreases linearly over controller.table_coloring_window
    ACTIVE_FUNCTION_COLOR = (100, 255, 100, 70)

    update_signal = Signal(list, list)

    def __init__(self, controller: BSController, col_headers=None, filter_cols=None, time_col=None, addr_col=None, parent=None):
        """
        Template class for a Binsync Table

        :param controller:    BinSyncController instance
        :param col_headers:   List of column header names
        :param col_dtypes:    List of data types (corresponding to the header names), supported
                              dtypes are {str, int, "time", "hex"}.
        :param addr_col:      (optional) Index of column containing addresses (if applicable)
        :param time_col:      (optional) Index of column containing times (if applicable)
        :param parent:        (optional) QT parent
        """
        super().__init__(parent)
        self.controller = controller
        self.row_data = []
        self.data_bgcolors = []
        self.data_tooltips = []

        self.col_headers = col_headers

        self.time_col = time_col
        self.addr_col = addr_col

        if isinstance(filter_cols, int):
            self.filter_cols = [filter_cols]
        else:
            self.filter_cols = filter_cols

        self.update_signal.connect(self.update_data)
        self.saved_color_window = self.controller.table_coloring_window

    def rowCount(self, index=QModelIndex()):
        """ Returns number of rows the model holds. """
        return len(self.row_data)

    def columnCount(self, index=QModelIndex()):
        """ Returns number of columns the model holds. """
        return len(self.col_headers)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        """ Set the headers to be displayed. """
        if role != Qt.DisplayRole:
            return None

        if orientation == Qt.Horizontal:
            if 0 <= section < len(self.col_headers):
                return self.col_headers[section]

        return None

    def insertRows(self, position, rows=1, index=QModelIndex()):
        """ Insert N (default=1) rows into the model at a desired position. """
        self.beginInsertRows(QModelIndex(), position, position + rows - 1)
        for row in range(rows):
            self.row_data.insert(position + row, [0]*self.columnCount())
            self.data_bgcolors.insert(position + row, [QColor(0, 0, 0, 0)])
        self.endInsertRows()
        return True

    def removeRows(self, position, rows=1, index=QModelIndex()):
        """ Remove N (default=1) rows from the model at a desired position. """
        if 0 <= position < len(self.row_data) and 0 <= position + rows < len(self.row_data):
            self.beginRemoveRows(QModelIndex(), position, position + rows - 1)
            del self.row_data[position:position + rows]
            del self.data_bgcolors[position:position + rows]
            self.endRemoveRows()
            return True
        return False

    def setData(self, index, value, role=Qt.EditRole):
        """ Adjust the data (set it to <value>) depending on the given
            index and role. """
        if role != Qt.EditRole:
            return False
        if index.isValid() and 0 <= index.row() < len(self.row_data):
            address = self.row_data[index.row()]
            if 0 <= index.column() < len(address):
                address[index.column()] = value
            else:
                return False
            self.dataChanged.emit(index, index)
            return True
        return False

    @Slot(list, list)
    def update_data(self, new_data, new_colors):
        prev_rc = len(self.row_data)
        new_rc = len(new_data)
        adding = prev_rc < new_rc
        removing = new_rc < prev_rc
        if adding:
            self.beginInsertRows(QModelIndex(), prev_rc, new_rc-1)
        elif removing:
            self.beginRemoveRows(QModelIndex(), new_rc, prev_rc-1)

        self.row_data = new_data
        self.data_bgcolors = new_colors

        if adding:
            self.endInsertRows()
        elif removing:
            self.endRemoveRows()

    def flags(self, index):
        """ Set the item flags at the given index. """
        if not index.isValid():
            return Qt.ItemIsEnabled
        return Qt.ItemFlags(QAbstractTableModel.flags(self, index))

    def data(self, index, role=Qt.DisplayRole):
        """ Returns information about the data at a specified index based
            on the role supplied. This function is performance sensitive. """
        raise NotImplementedError

    def refresh_time_cells(self):
        # always update every column in the table that contains time
        self.dataChanged.emit(
            self.createIndex(0, self.time_col),
            self.createIndex(self.rowCount() - 1, self.time_col)
        )

    def _update_changed_rows(self, row_data: Dict, updated_row_keys: Set):
        # user may have changed how dark he wants colors to go (color window)
        force_color_update = self.controller.table_coloring_window != self.saved_color_window

        # no changes are required
        if not updated_row_keys and not force_color_update:
            return False

        row_colors = [
            self._compute_row_color(row[self.time_col]) for row in row_data.values()
        ]

        if force_color_update:
            # update all rows
            self.saved_color_window = self.controller.table_coloring_window
            row_update_idxs = range(len(row_data))
        else:
            # update only rows with changes
            row_update_idxs = [
                idx for idx, row_key in enumerate(row_data.keys())
                if row_key in updated_row_keys
            ]

        # send update signal for everything in row data, with new colors
        self.update_signal.emit(list(row_data.values()), row_colors)

        # ask for in-row updates (in UI) to any single row changed
        for update_idx in row_update_idxs:
            self.dataChanged.emit(self.index(0, update_idx), self.index(self.rowCount() - 1, update_idx))

    def _compute_row_color(self, artifact_update_time: datetime.datetime):
        if artifact_update_time is not None:
            duration = int(datetime.datetime.now(tz=datetime.timezone.utc).timestamp() - artifact_update_time.timestamp())
        else:
            duration = -1

        if 0 <= duration <= self.controller.table_coloring_window:
            opacity = (self.controller.table_coloring_window - duration) / self.controller.table_coloring_window
            return QColor(
                BinsyncTableModel.ACTIVE_FUNCTION_COLOR[0],
                BinsyncTableModel.ACTIVE_FUNCTION_COLOR[1],
                BinsyncTableModel.ACTIVE_FUNCTION_COLOR[2],
                int(BinsyncTableModel.ACTIVE_FUNCTION_COLOR[3] * opacity)
            )

        return None

    def update_table(self, states):
        """ Updates the table using the controller's information. """
        raise NotImplementedError


class BinsyncTableFilterLineEdit(QLineEdit):
    """ Basic class for the filter line edit, clears itself whenever focus is lost. """

    def __init__(self, parent=None):
        super(BinsyncTableFilterLineEdit, self).__init__(parent=parent)
        self.user_unfocused = False

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self.user_unfocused:
            self.user_unfocused = False
            self.clear()

        if event.key() == Qt.Key_Escape:
            self.clear()
            return
        super(BinsyncTableFilterLineEdit, self).keyPressEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        if event.reason() == Qt.MouseFocusReason:
            self.user_unfocused = True
        super(BinsyncTableFilterLineEdit, self).focusOutEvent(event)


class BinsyncTableView(QTableView):
    """ Table view for the data, this is the front end "container" for our model. """

    def __init__(self, controller: BSController, filteredit: BinsyncTableFilterLineEdit=None, stretch_col=None, col_count=None, parent=None):
        """
        Template class for a Binsync Table View, required to create and set the model (extend BinsyncTableModel)

        :param controller:    BinSyncController instance
        :param filteredit:    An instance of BinsyncTableFilterLineEdit
        :param stretch_col:   Column to stretch (resize) when table is resized
        :param col_count:     Number of columns this table will have
        :param parent:        (optional) QT parent

        """
        super().__init__(parent=parent)

        self.controller = controller

        self.filteredit = filteredit
        if self.filteredit is not None:
            self.filteredit.textChanged.connect(self.handle_filteredit_change)

        # Create a SortFilterProxyModel to allow for sorting/filtering
        self.proxymodel = QSortFilterProxyModel()
        # Set the sort role/column to filter by
        self.proxymodel.setSortRole(BinsyncTableModel.SortRole)
        self.proxymodel.setFilterRole(BinsyncTableModel.FilterRole)
        self.proxymodel.setFilterKeyColumn(0)

        self.setModel(self.proxymodel)

        self.doubleClicked.connect(self._doubleclick_handler)
        self.column_visibility = []

        self.stretch_col = stretch_col
        self.col_count = col_count

    def _doubleclick_handler(self):
        """ Handler for double clicking on a row, jumps to the respective function. """
        if self.model.addr_col is None:
            return
        row_idx = self.selectionModel().selectedIndexes()[0]
        tls_row_idx = self.proxymodel.mapToSource(row_idx)
        row = self.model.row_data[tls_row_idx.row()]
        self.controller.deci.gui_goto(row[self.model.addr_col])

    def _selected_source_rows(self):
        if self.selectionModel() is None:
            return []

        selected_rows = self.selectionModel().selectedRows()
        if not selected_rows:
            selected_rows = [index for index in self.selectionModel().selectedIndexes() if index.column() == 0]

        unique_rows = []
        seen_rows = set()
        for proxy_index in selected_rows:
            source_index = self.proxymodel.mapToSource(proxy_index)
            if not source_index.isValid() or source_index.row() in seen_rows:
                continue

            seen_rows.add(source_index.row())
            unique_rows.append(source_index)

        return unique_rows

    def _toggle_selected_check_states(self):
        source_rows = self._selected_source_rows()
        if not source_rows or not hasattr(self.model, "checkStateBool"):
            return False

        first_row = source_rows[0]
        target_state = not self.model.checkStateBool(first_row)
        return self._set_check_states_for_source_indexes(source_rows, target_state)

    def _checked_source_indexes(self, check_column=0):
        checked_indexes = []

        for row_idx in range(self.model.rowCount()):
            source_index = self.model.index(row_idx, check_column, QModelIndex())
            model_state = self.model.checkState(source_index)
            is_checked = model_state.value if hasattr(model_state, "value") else model_state
            if is_checked:
                checked_indexes.append(source_index)

        return checked_indexes

    def _clear_checked_source_indexes(self, source_indexes):
        return self._set_check_states_for_source_indexes(source_indexes, False)

    def _set_check_states_for_source_indexes(self, source_indexes, value):
        if not source_indexes:
            return False

        if hasattr(self.model, "setCheckStatesForIndexes"):
            self.setUpdatesEnabled(False)
            try:
                changed = self.model.setCheckStatesForIndexes(source_indexes, value)
            finally:
                self.setUpdatesEnabled(True)
                self.viewport().update()

            return changed

        changed = False
        for source_index in source_indexes:
            changed |= self.model.setData(source_index, value, role=Qt.CheckStateRole)

        return changed

    def _run_with_busy_cursor(self, callback):
        app = QApplication.instance()
        if app is None:
            return callback()

        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        app.processEvents()
        try:
            return callback()
        finally:
            QApplication.restoreOverrideCursor()
            app.processEvents()

    def mousePressEvent(self, event) -> None:
        clicked_index = self.indexAt(event.pos())
        if clicked_index.isValid() and clicked_index.column() == 0:
            source_rows = self._selected_source_rows()
            source_index = self.proxymodel.mapToSource(clicked_index)
            if len(source_rows) > 1 and any(row.row() == source_index.row() for row in source_rows):
                if self._toggle_selected_check_states():
                    event.accept()
                    return

        super().mousePressEvent(event)

    def _col_hide_handler(self, index):
        """ Helper function to hide/show columns from context menu """
        self.column_visibility[index] = not self.column_visibility[index]
        self.setColumnHidden(index, self.column_visibility[index])
        if self.column_visibility[index]:
            self.showColumn(index)
        else:
            self.hideColumn(index)

    def update_table(self, states):
        """ Update the model of the table with new data from the controller """
        self.model.update_table(states)

    def reload(self):
        pass

    def contextMenuEvent(self, event):
        raise NotImplementedError

    def _init_settings(self):
        self.setShowGrid(False)

        header = self.horizontalHeader()
        header.setSortIndicator(0, Qt.AscendingOrder)
        for i in range(self.col_count):
            self.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(self.stretch_col, QHeaderView.Stretch)

        self.column_visibility = [True for _ in range(self.col_count)]

        fixed_width_font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        fixed_width_font.setPointSize(11)
        self.setFont(fixed_width_font)

        self.setSortingEnabled(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)

        self.setWordWrap(False)

        vheader = self.verticalHeader()
        vheader.setDefaultSectionSize(24)
        vheader.hide()

        self.setFocusProxy(self.filteredit)

    def handle_filteredit_change(self, text):
        """ Handle text changes in the filter box, filters the table by the arg. """
        self.proxymodel.setFilterFixedString(text)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            if self._toggle_selected_check_states():
                event.accept()
                return

        super().keyPressEvent(event)
