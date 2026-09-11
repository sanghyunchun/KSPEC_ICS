import sys
import os
import asyncio

from PySide6.QtCore import *
from PySide6.QtWidgets import (
        QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget, QMessageBox, QSizePolicy, QFileDialog, QListWidget,QListWidgetItem,
        QDialog, QTextEdit
        )
from PySide6.QtGui import QMouseEvent, QGuiApplication, QTextCursor, QFont
from ui_mainwindow import Ui_MainWindow
from qasync import QEventLoop, asyncSlot
from astropy.io import fits
from astropy.coordinates import Angle, SkyCoord
import astropy.units as u
import Lib.mkmessage as mkmsg
import Lib.zscale as zs
from Lib.updatelog import obslog
from Lib.make_spec_header import set_header_info
import json
from aio_pika import IncomingMessage

from datetime import datetime, timezone
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import numpy as np
from Lib.AMQ import AMQclass, UDPClientProtocol, TCPClient
from ADC.adccli import handle_adc
from GFA.gfacli import handle_gfa
from FBP.fbpcli import handle_fbp
from MTL.mtlcli import handle_mtl
from LAMP.lampcli import handle_lamp
from SPECTRO.speccli import handle_spec
from TCS.tcscli import handle_telcom
from script.scriptcli import handle_script
from script.scriptcli import script
from SCIOBS.sciobscli import sciobscli


### Canvas Setting ###
class MplCanvas(FigureCanvas):
    def __init__(self, parent=None,dpi=100,left=0.00,right=1.,bottom=0.0,top=1.):
        self.fig = Figure(dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        self.fig.subplots_adjust(left=left,right=right,bottom=bottom,top=top) 
        self.ax.axis('off')
        super().__init__(self.fig)
        self.setParent(parent)

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.updateGeometry()

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFocus()
        self._is_dragging = False
        self._last_mouse_pos = None

        # Set inital axis range
        self._initial_xlim = None
        self._initial_ylim = None

    def imshows(self, data, **kwargs):
        self.ax.clear()
        self.ax.imshow(data, **kwargs)
        self.ax.axis('on')
        self.fig.subplots_adjust(left=0.05,right=1,bottom=0.05, top=1)
        self._initial_xlim = self.ax.get_xlim()
        self._initial_ylim = self.ax.get_ylim()
        self.draw()

    def plots(self,wave,flux):
        self.ax.clear()
        self.ax.plot(wave,flux,'k-')
        self.ax.axis('on')
        self.draw()

    def wheelEvent(self, event):
        # Expand and contract
        x_min, x_max = self.ax.get_xlim()
        y_min, y_max = self.ax.get_ylim()
        zoom_factor = 0.9 if event.angleDelta().y() > 0 else 1.1

        x_center = (x_min + x_max) / 2
        y_center = (y_min + y_max) / 2
        x_range = (x_max - x_min) * zoom_factor
        y_range = (y_max - y_min) * zoom_factor

        self.ax.set_xlim([x_center - x_range / 2, x_center + x_range / 2])
        self.ax.set_ylim([y_center - y_range / 2, y_center + y_range / 2])
        self.draw()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = True
            self._last_mouse_pos = event.position()
        elif event.button() == Qt.MouseButton.RightButton:
            # Right click for reset
            if self._initial_xlim and self._initial_ylim:
                self.ax.set_xlim(self._initial_xlim)
                self.ax.set_ylim(self._initial_ylim)
                self.draw()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._is_dragging and self._last_mouse_pos:
            current_pos = event.position()
            dx = current_pos.x() - self._last_mouse_pos.x()
            dy = current_pos.y() - self._last_mouse_pos.y()

            x_min, x_max = self.ax.get_xlim()
            y_min, y_max = self.ax.get_ylim()
            x_range = x_max - x_min
            y_range = y_max - y_min

            self.ax.set_xlim(x_min - dx * x_range / self.width(), x_max - dx * x_range / self.width())
            self.ax.set_ylim(y_min + dy * y_range / self.height(), y_max + dy * y_range / self.height())
            self.draw()

            self._last_mouse_pos = current_pos

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = False



class SelectTile(QDialog):
    def __init__(self, headers, data_lines, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Observation Plan file")
        self.selected_values = None

        self.list_widget = QListWidget()

        for line in data_lines:
            values = line.strip().split()
            # 헤더와 값 결합
            display_line = "   ".join(f"{h}: {v}" for h, v in zip(headers, values))
            item = QListWidgetItem(display_line)
            item.setData(32, values)  # Qt.UserRole = 32 → 원본 값 저장
            self.list_widget.addItem(item)

        self.list_widget.itemDoubleClicked.connect(self.select_row)

        layout = QVBoxLayout()
        layout.addWidget(self.list_widget)
        self.setLayout(layout)
        self.resize(600, 400)

    def select_row(self, item):
        self.selected_values = item.data(32)
        self.accept()


class MainWindow(QMainWindow):

    # region Initialization and GUI setup
    def __init__(self):

        super(MainWindow, self).__init__()
        self.setWindowTitle("K-SPEC ICS")
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.scriptrun=script()
        self.ICS_client = None

        QTimer.singleShot(0, self.adjust_window_size_by_screen)

        ### All Response queue of asyncio ###
        self.response_queue = asyncio.Queue()
        self.GFA_response_queue = asyncio.Queue()
        self.ADC_response_queue = asyncio.Queue()
        self.SPEC_response_queue = asyncio.Queue()

        ### Observation Setting ###
        self.observer = None
        self.obsdir = None
        self.command_list = self.load_command_list()
        self.tcsagentIP, self.tcsagentPort, self.telcomIP, self.telcomPort = self.load_config()

        self.gfaexpt = None
        self.gfacam = 0
        self.adc = 0
        
        self.mtlexp = None
        self.msglog_path = None
        self.ra = None
        self.dec = None
        self.obstype = None
        self.TileID = None
        self.expT = None
        self.expnum = None
        self.obsnum = None
        self.project = None
        self.fwhm = None
        self.object = None
        self.obslog = None

        ### Instrument position state & state ###
        self.adcadjusting_state = False
        self.fbp_state = False
        self.find_state = False
        self.mtl_state = False
        self.guiding_state = False
        self.arc_state = False
        self.flat_state = False
        self.fiducial_state = False
#        self.fbp_restore = False
    

#       Make timer (LT & UTC) 
        self.datetime = QDateTime.currentDateTime().toString()
        #self.lcd.display(datetime)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.timeout)
        self.setWindowTitle('KSPEC ICS')
        self.timer.start()

        self._setup_buttons()
        self._setup_canvases()

    def _setup_buttons(self):
        """Connect GUI widgets to their handlers."""
        # Setting Initial observation
        self.ui.pushbtn_connect.setCheckable(True)
        self.ui.pushbtn_connect.clicked.connect(self.rabbitmq_connect)
        #    self.ui.pushbtn_observer.clicked.connect(self.save_observer)
        self.ui.pushbtn_directory.clicked.connect(self.set_directory)
        self.ui.pushbtn_syscheck.clicked.connect(self.syscheck)


        # GFA & Guiding
        self.ui.pushbtn_Guiding.setCheckable(True)
        self.ui.pushbtn_Guiding.clicked.connect(self.Guiding_button_clicked)
        self.ui.pushbtn_Guiding_2.setCheckable(True)
        self.ui.pushbtn_Guiding_2.clicked.connect(self.Guiding_button_clicked)

        self.ui.pushbtn_GFArun.clicked.connect(self.GFArun_button_clicked)
        self.ui.pushbtn_GFA_set.clicked.connect(self.GFA_set_button_clicked)



        # Pointing and Astrometry
        self.ui.pushbtn_caloffset.clicked.connect(self.caloffset_button_clicked)
        self.ui.pushbtn_pointing.clicked.connect(self.pointing_button_clicked)


        #    # Finder
        #    self.ui.pushbtn_finder_exp.clicked.connect(self.finder_button_clicked)


        # ADC adjust
        self.ui.pushbtn_ADCadjust.setCheckable(True)
        self.ui.pushbtn_ADCadjust.clicked.connect(self.ADCadjust_button_clicked)
        self.ui.pushbtn_ADCadjust_2.setCheckable(True)
        self.ui.pushbtn_ADCadjust_2.clicked.connect(self.ADCadjust_button_clicked)

        self.ui.pushbtn_adc_rotate.clicked.connect(self.adcrotate_button_clicked)
        self.ui.pushbtn_adc_park.clicked.connect(self.adcpark_button_clicked)
        self.ui.pushbtn_adc_home.clicked.connect(self.adchome_button_clicked)
        self.ui.pushbtn_adc_zero.clicked.connect(self.adczero_button_clicked)
        self.ui.pushbtn_adc_connect.clicked.connect(self.adcconnect_button_clicked)



        # Fiber assign
        self.ui.pushbtn_FBP_zero.clicked.connect(self.FBP_zero_button_clicked)
        #    self.ui.pushbtn_FBP_offset.clicked.connect(self.FBP_offset_button_clicked)
        self.ui.pushbtn_FBP_status.clicked.connect(self.FBP_Status_button_clicked)
        self.ui.pushbtn_FBP_rotate.clicked.connect(self.FBP_rotate_button_clicked)

        #    self.ui.pushbtn_FBP_assign.setCheckable(True)
        self.ui.pushbtn_FBP_assign.clicked.connect(self.FBP_assign_button_clicked)
        #    self.ui.pushbtn_FBP_assign_2.setCheckable(True)
        self.ui.pushbtn_FBP_assign_2.clicked.connect(self.FBP_assign_button_clicked)

        self.ui.pushbtn_FBP_initial.clicked.connect(self.FBP_initial_button_clicked)
        self.ui.pushbtn_FBP_stop.clicked.connect(self.FBP_stop_button_clicked)

        self.ui.pushbtn_FBP_lock.clicked.connect(self.FBP_lock_button_clicked)




        # MTL
        self.ui.pushbtn_MTL_exp.clicked.connect(self.MTL_exp_button_clicked)
        #    self.ui.pushbtn_MTL_exp_2.clicked.connect(self.MTL_exp_button_clicked)
        #    self.ui.pushbtn_MTL_exp_3.clicked.connect(self.MTL_exp_button_clicked)

        self.ui.pushbtn_MTL_cal.clicked.connect(self.MTL_cal_button_clicked)
        self.ui.pushbtn_MTL_set.clicked.connect(self.MTL_set_button_clicked)


        # Load Sequence
        self.ui.pushbtn_load_sequence.clicked.connect(self.load_file)
        self.ui.pushbtn_set_sequence.clicked.connect(self.load_tile)


        # Take and show spectro images
        self.ui.pushbtn_run_obs.clicked.connect(self.run_obs_clicked)
        self.ui.pushbtn_run_calib.clicked.connect(self.take_calib)

        self.ui.pushbtn_exp_start.clicked.connect(self.exp_start_clicked)

        self.ui.pushbtn_show_spec.clicked.connect(self.show_spec)

        # LAMP
        self.ui.pushbtn_Flat.setCheckable(True)
        self.ui.pushbtn_Flat_2.setCheckable(True)
        self.ui.pushbtn_Flat.clicked.connect(self.flat_button_clicked)
        self.ui.pushbtn_Flat_2.clicked.connect(self.flat_button_clicked)

        self.ui.pushbtn_Arc.setCheckable(True)
        self.ui.pushbtn_Arc_2.setCheckable(True)
        self.ui.pushbtn_Arc.clicked.connect(self.arc_button_clicked)
        self.ui.pushbtn_Arc_2.clicked.connect(self.arc_button_clicked)

        self.ui.pushbtn_Fiducial.setCheckable(True)
        self.ui.pushbtn_Fiducial_2.setCheckable(True)
        self.ui.pushbtn_Fiducial.clicked.connect(self.fiducial_button_clicked)
        self.ui.pushbtn_Fiducial_2.clicked.connect(self.fiducial_button_clicked)


        # Telescope slew
        self.ui.pushbtn_slew.clicked.connect(self.slew_button_clicked)


        #    # Focusing
        #    self.ui.pushbtn_dfp5.clicked.connect(self.dfp5_button_clicked)
        #    self.ui.pushbtn_dfm5.clicked.connect(self.dfm5_button_clicked)
        #    self.ui.pushbtn_dfp005.clicked.connect(self.dfp005_button_clicked)
        #    self.ui.pushbtn_dfm005.clicked.connect(self.dfm005_button_clicked)
        #    self.ui.pushbtn_fttgoto.clicked.connect(self.fttgoto_button_clicked)

        # CLI command
        self.ui.pushbtn_send_cmd.clicked.connect(self.user_input)
        self.ui.pushbtn_send_cmd_2.clicked.connect(self.user_input)

        # Observer Comment
        self.ui.pushbtn_send_comment_1.clicked.connect(self.comment1_clicked)
        self.ui.pushbtn_send_comment_2.clicked.connect(self.comment2_clicked)


        # System status button
        self.ui.pushbtn_reset1.clicked.connect(self.reset_status)
        self.ui.pushbtn_reset2.clicked.connect(self.reset_status)

    def _setup_canvases(self):
        """Create matplotlib canvases embedded in the GUI."""
        self.canvas_B=MplCanvas(self,dpi=100,left=0.00,right=1.,bottom=0.0,top=1.)
        self.B_layout=QVBoxLayout(self.ui.frame_B)
        self.B_layout.addWidget(self.canvas_B)

        self.canvas_R=MplCanvas(self,dpi=100,left=0.00,right=1.,bottom=0.0,top=1.)
        self.R_layout=QVBoxLayout(self.ui.frame_R)
        self.R_layout.addWidget(self.canvas_R)

    def adjust_window_size_by_screen(self):
        screen = QGuiApplication.primaryScreen()
        geometry = screen.availableGeometry()

        # Window size
        screen_width = geometry.width()
        screen_height = geometry.height()

        window_width = int(screen_width * 0.5)
        window_height = int(screen_height * 0.5)

        self.resize(window_width, window_height)

    def timeout(self):
        sender = self.sender()
        self.currentTime = QDateTime.currentDateTime().toString('yyyy.MM.dd, hh:mm:ss')
        self.currentutc = QDateTime.currentDateTimeUtc().toString('yyyy.MM.dd, hh:mm:ss')
        #print(currentTime)
        if id(sender) == id(self.timer):
            self.ui.lcd_lt.display(self.currentTime)
            self.ui.lcd_utc.display(self.currentutc)

    def closeEvent(self, QCloseEvent):
        re = QMessageBox.question(self, "Close the program", "Are you sure you want to quit?",
                    QMessageBox.Yes|QMessageBox.No)

        if re == QMessageBox.Yes:
            QCloseEvent.accept()
        else:
            QCloseEvent.ignore()

    # endregion Initialization and GUI setup

    # region Logging, dialogs, and config
    def logging(self,message,status: str='success', level: str='send', save: str=True):
        if isinstance(message,dict):
            message=json.dumps(message)

        color_map={
                "send": "green", "receive": "blue", "error": "red", "warning": "orange",
        }

        if status == "error":
            level = 'error'

        color = color_map.get(level,"black")

        self.uttime = QDateTime.currentDateTimeUtc().toString('hh:mm:ss.ss')
        self.ui.log1.append(f'<span style="color:{color};">[{self.uttime}][ICS] {message}</span>')
        self.ui.log2.append(f'<span style="color:{color};">[{self.uttime}][ICS] {message}</span>')
        self.ui.log1.moveCursor(QTextCursor.End)
        self.ui.log2.moveCursor(QTextCursor.End)

        if save :
            with open(self.msglog_path,'a') as f:
                f.write(f'[{self.uttime}][ICS] {message}\n')

    def set_directory(self): 
        current_dir=os.getcwd()
        parent_dir = os.path.dirname(current_dir)
        self.dir_name=self.ui.lineEdit_directory.text()

        msglogfile = 'MSGLOG_'+self.dir_name+'.txt'
        self.msglog_path=os.path.join(parent_dir,"DATA/MSGLOG",msglogfile)
        if os.path.exists(self.msglog_path):
            self.logging(f"Message Log file'{msglogfile}' already exists.", level='normal')
            pass
        else:
            with open(self.msglog_path,'w') as f:
                pass
                self.logging(f"Message Log file '{msglogfile}' was created.", level='normal')

        self.dir_path=os.path.join(parent_dir,"DATA/RAWDATA",self.dir_name)
        if os.path.exists(self.dir_path):
            self.logging(f"Directory '{self.dir_path}' already exists.", level='normal')
            pass
        else:
            os.makedirs(self.dir_path, exist_ok=True)
            self.logging(f"Create directory '{self.dir_path}'.",level='normal')

    def show_command_popup(self):
        file_path = "./Lib/command.txt"

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            content = f"Failed to read file:\n{e}"

        dialog = QDialog(self)
        dialog.setWindowTitle("K-SPEC Command list")
        dialog.resize(600, 900)

        layout = QVBoxLayout(dialog)

        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(content)

        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.close)

        layout.addWidget(text_edit)
        layout.addWidget(close_button)

        dialog.setModal(True)
        dialog.open()

    def show_inst_command_popup(self,instrument):
        if instrument == "ADC?":
            file_path = "./Lib/ADCcommand.txt"
        elif instrument == 'GFA?':
            file_path = "./Lib/GFAcommand.txt"
        elif instrument == 'LAMP?':
            file_path = "./Lib/LAMPcommand.txt"
        elif instrument == 'MTL?':
            file_path = "./Lib/MTLcommand.txt"

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            content = f"Failed to read file:\n{e}"

        inst = instrument.rstrip("?")
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{inst} Command Usages")
        dialog.resize(600, 900)

        layout = QVBoxLayout(dialog)

        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(content)

        font = QFont("Courier New")
        font.setStyleHint(QFont.Monospace)
        text_edit.setFont(font)

        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.close)

        layout.addWidget(text_edit)
        layout.addWidget(close_button)

        dialog.setModal(True)
        dialog.open()

    def comment1_clicked(self):
        comment=self.ui.lineEdit_comment_1.text()
        self.logging(f"Observer comment '{comment}'.",level='comment')
        self.ui.lineEdit_comment_1.clear()

    def comment2_clicked(self):
        comment=self.ui.lineEdit_comment_2.text()
        self.logging(f"Observer comment '{comment}'.",level='comment')
        self.ui.lineEdit_comment_2.clear()

    def sync_queue_mode(self):
        self.ui.lineEdit_CProj.clear()
        self.ui.lineEdit_CTile.clear()
        self.ui.lineEdit_TileID.clear()
        self.ui.lineEdit_exp_time_1.clear()
        self.ui.lineEdit_n_exp_1.clear()
        self.ui.lineEdit_ra_1.setText(self.ra)
        self.ui.lineEdit_dec_1.setText(self.dec)
        self.ui.lineEdit_offset.clear()
        self.ui.lineEdit_raoffset.clear()
        self.ui.lineEdit_decoffset.clear()

    def handle_utils(self, message):
        if message == "?":
            self.show_command_popup()
        else:
            self.show_inst_command_popup(message)
        return

    def load_command_list(self):
        return {
            "adc": ["adcstatus", "adcactivate", "adcadjust", "adcconnect", "adcdisconnect", "adchome", "adczero",
            "adcpoweroff", "adcrotate1", "adcrotate2", "adcstop", "adcpark", "adcctrotate", "adccorotate"],
            "gfa": ["gfastatus", "gfagrab", "fdgrab"],
            "fbp": ["fbpstatus", "fbpzero", "fbpmove", "fbpoffset"],
            "mtl": ["mtlstatus", "mtlexp", "mtlcal"],
            "lamp": ["lampstatus", "arcon", "arcoff", "flaton", "flatoff","fiducialon","fiducialoff"],
            "spec": ["specstatus", "specinitial","illuon", "illuoff", "getobj", "getbias", "getflat","getar"],
            "tcs": ["tmradec", "start", "stop", "tcsint", "tcsreset", "tcsclose",
            "tcsarc", "tcsstatus", "tstat", "traw", "tsync", "tcmd",
            "treg", "tmradec", "tmr", "tmobject", "tmo", "tmelaz",
            "tme", "tmoffset", "toff", "tstop", "tstow", "tdi",
            "cc", "oo", "nstset", "nston", "nstoff", "auxinit",
            "auxreset", "auxclose", "auxarc", "auxstatus",
            "astat", "acmd", "fsastat", "fs", "fttstat",
            "ft", "dfocus", "dtilt", "fttgoto"],

            "telcom": ["getall", "getra", "getdec", "getha", "getel", "getaz", "getsecz", "mvstow", "mvelaz", "mvstop", "mvra", "mvdec", "track", "stepra", "stepdec"],
            "utils": ["?","obsstatus","loadtile","setdir", "ADC?", "GFA?", "LAMP?", "MTL?", "FBP?", "SPEC?"],
            "script": ["runcalib", "obsinitial", "autoguide", "autoguidestop", "runobs"]
            }

    def load_config(self):
        """Loads configuration settings from KSPEC.ini."""
        with open('./Lib/KSPEC.ini', 'r') as f:
            kspecinfo = json.load(f)

        return (
            kspecinfo['TCS']['TCSagentIP'],
            kspecinfo['TCS']['TCSagentPort'],
            kspecinfo['TCS']['TelcomIP'],
            kspecinfo['TCS']['TelcomPort']
        )

    def find_category(self, cmd):
        """Finds the category of a given command."""
        return next((cat for cat, cmds in self.command_list.items() if cmd in cmds), None)

    # endregion Logging, dialogs, and config

    # region Connection and command routing
    @asyncSlot()
    async def rabbitmq_connect(self):
        if self.msglog_path == None:
            self.logging("Obseveing directory was not set. Please insert directory.",level='error',save=False)
            self.ui.pushbtn_connect.setChecked(False)
            return
        else:
            if self.ui.pushbtn_connect.isChecked():
                self.ui.pushbtn_connect.setText('Connecting')
                self.ui.pushbtn_connect.setStyleSheet('color: orange;')

                client = None
                try:
                    #    print(f'Observer Name: {self.observer}')
                    # Connect RabbitMQ
                    with open('./Lib/KSPEC.ini', 'r') as f:
                        kspecinfo = json.load(f)

                    client = AMQclass(
                        kspecinfo['RabbitMQ']['ip_addr'],
                        kspecinfo['RabbitMQ']['idname'],
                        kspecinfo['RabbitMQ']['pwd'],
                        'ICS', 'ics.ex'
                    )

                    react = await client.connect()
                    self.logging(react,level='AMQ')
                    react = await client.define_producer()
                    self.logging(react,level='AMQ')

                    await client.define_consumer('ICS',self.on_ics_message)
                    self.ICS_client = client
                    self.ui.pushbtn_connect.setText('Connected')
                    self.ui.pushbtn_connect.setStyleSheet('color: green;')

                except Exception as e:
                    self.logging(f"RabbitMQ connection failed: {e}", level='error')
                    self.ui.pushbtn_connect.setChecked(False)
                    self.ui.pushbtn_connect.setText('Connect')
                    self.ui.pushbtn_connect.setStyleSheet('color: black;')
                    self.ICS_client = None

                    if client is not None:
                        try:
                            await client.disconnect()
                        except Exception as close_error:
                            self.logging(f"RabbitMQ cleanup failed: {close_error}", level='warning')

            else:
                try:
                    if self.ICS_client is not None:
                        await self.ICS_client.disconnect()
                except Exception as e:
                    self.logging(f"RabbitMQ disconnect failed: {e}", level='error')
                finally:
                    self.ui.pushbtn_connect.setText('Connect')
                    self.ui.pushbtn_connect.setStyleSheet('color: black;')
                    self.ui.pushbtn_connect.setChecked(False)
                    self.ICS_client = None

    def check_connection(self):
        client = getattr(self,'ICS_client',None)
        connection = getattr(client,'connection',None) if client else None
        channel = getattr(client,'channel',None) if client else None
        connection_closed = getattr(connection,'is_closed',True)
        channel_closed = getattr(channel,'is_closed',True)

        if not client or connection is None or channel is None or connection_closed or channel_closed:
            self.logging("ICS_client is not connected to RabbitMQ server. Please click 'connect' button.", level='error')
            self.ui.pushbtn_connect.setText('Connect')
            self.ui.pushbtn_connect.setStyleSheet('color: black;')
            self.ui.pushbtn_connect.setChecked(False)
            self.ICS_client = None
            return False
        return True

    def check_syscheck(self):
        if not getattr(self,'dependencies', False):
            self.logging("Systems are not checked. Please click 'Sys check' button.", level='error')
            return False
        return True

    def _log_received_message(self, inst, msg, status):
        if isinstance(msg, dict):
            log_msg = json.dumps(msg, indent=2)
        else:
            log_msg = str(msg)

        print(
            f"\033[94m[ICS] received from {inst}: {log_msg}\033[0m\n",
            flush=True,
        )

        if status == "error":
            log_level = "error"

        elif status == "fail":
            log_level = "warning"

        else:
            log_level = "receive"

        self.logging(log_msg, status, level=log_level)

    async def _handle_in_progress_response(self, response_data, inst, process):
        queue_map = {
            "GFA": self.GFA_response_queue,
            "ADC": self.ADC_response_queue,
            "SPEC": self.SPEC_response_queue,
        }

        if inst not in queue_map or process not in ("ING", "START"):
            return False

        await queue_map[inst].put(response_data)

        if inst == "GFA" and process == "ING":
            fwhm = response_data.get("fwhm")
            if fwhm is not None:
                try:
                    fwhm_value = float(fwhm)
                except (TypeError, ValueError):
                    fwhm_value = None

                if fwhm_value is not None and np.isfinite(fwhm_value):
                    self.fwhm = round(fwhm_value, 2)
                    # self.ui.lineEdit_seeing.setText(f"{self.fwhm}")
                    # self.show_guiding()

        return True

    async def _handle_gfa_guiding_terminal_response(self, response_data, inst, process, status, msg):
        if inst != "GFA" or process != "Done" or status not in ("warning", "error", "fail"):
            return False

        if "guid" not in str(msg).lower():
            return False

        await self.GFA_response_queue.put(response_data)
        await self.response_queue.put(response_data)
        return True

    async def on_ics_message(self, message: IncomingMessage):
        async with message.process():
            try:
                response_data = json.loads(message.body)

                inst = response_data.get("inst", "None")
                process = response_data.get("process", "None")
                status = response_data.get("status", "fail")
                subinst = response_data.get("subinst", "None")
                msg = response_data.get("message", "None")

                print(response_data)

                # 1. 상태 업데이트
                self.set_inst_pos_state(response_data)
                self.show_status(response_data)

                # 2. 수신 로그 출력
                self._log_received_message(inst, msg, status)

                # 3. 진행 중 메시지는 각 장비별 queue로 전달
                if await self._handle_in_progress_response(response_data, inst, process):
                    return

                # 4. GFA POINT 완료 처리
                if inst == "GFA" and process == "Done" and subinst == "POINT":
                    await self._handle_gfa_point_response(response_data, status)
                    return

                # 5. GFA guiding terminal warning/error 처리
                if await self._handle_gfa_guiding_terminal_response(response_data, inst, process, status, msg):
                    return

                # 5. SPEC image 처리
                if inst == "SPEC" and response_data.get("filename") != "None":
                    self.show_spec(response_data)
                    await self.response_queue.put(response_data)
                    return

                # 6. FBP 처리
            #    if inst == "FBP" and 'data' in response_date:

                # 6. 그 외 일반 응답
                await self.response_queue.put(response_data)

            except Exception as e:
                print(f"Error in on_ics_message: {e}", flush=True)
                self.logging(f"Error in on_ics_message: {e}", "fail", level="error")

    async def send_udp_message(self, message):
        """
        Sends a message to the TCS Agent via UDP using UDPClientProtocol 
        """
        loop = asyncio.get_running_loop()
        on_con_lost = loop.create_future()
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: UDPClientProtocol(on_con_lost),
            remote_addr=(self.tcsagentIP, self.tcsagentPort)
        )

        print(f"\033[32m[ICS] sent TCS message to TCS Agent: {message}\033[0m", flush=True)
        self.logging(f'sent TCS message to TCS Agent: {message}',level='send')
        transport.sendto(message.encode())
        transport.close()

    async def send_telcom_command(self,message):
        """Sends a command to the Telcom system via TCP."""
        telcom_client = TCPClient(self.telcomIP,self.telcomPort)
        await telcom_client.connect()
        result = await handle_telcom(message,telcom_client)
        await telcom_client.close()
        self.ui.lineEdit_cmd.clear()
        self.ui.lineEdit_cmd_2.clear()
        return result

    async def send_command(self, category, message):
        """
        Sends a command using the respective handler.
        """
        category = category.lower()

        general_handlers = {
            "adc": handle_adc, "gfa": handle_gfa, "fbp": handle_fbp,
            "mtl": handle_mtl, "lamp": handle_lamp,
            "spec": handle_spec,
        }

        if category == "utils":
            self.handle_utils(message)
            return

        if category == "script":
            script_cmd = message.split()[0]
            if script_cmd == 'runobs' and not self.sync_script_observation_context():
                return
            self.scriptrun.fwhm = self.fwhm
            self.scriptrun.obslog = self.obslog
            await handle_script(message, scriptrun=self.scriptrun, logging=self.logging)
            return

        handler = general_handlers.get(category)
        if handler is None:
            print(f"Unknown command category: {category}", flush=True)
            return

        await handler(message, self.ICS_client)

    @asyncSlot()
    async def user_input(self):
        """
        Handles user input asynchronously, allowing immediate command sending.
        """
        try:
            sys.stdout.flush()

            message = self.ui.lineEdit_cmd.text().strip() or self.ui.lineEdit_cmd_2.text().strip()
                
            cmd = message.split(" ")[0]
            category = self.find_category(cmd)
            print(f'Command Category is {category}', flush=True)

            if category:
                if category.lower() == 'tcs':
                    messagetcs = 'KSPEC>TC ' + message
                    await self.send_udp_message(messagetcs)
                    self.ui.lineEdit_cmd.clear()
                    self.ui.lineEdit_cmd_2.clear()
                elif category.lower() == 'telcom':
                    telcom_result = await self.send_telcom_command(message)
                    print('\033[94m' + '[ICS] received: ', telcom_result.decode() + '\033[0m', flush=True)
                    self.logging(telcom_result.decode(), level='receive')
                else:
                    await self.send_command(category, message)

                self.ui.lineEdit_cmd.clear()
                self.ui.lineEdit_cmd_2.clear()
            else:
                print("Invalid command. Please enter a valid command.\n", flush=True)
        except Exception as e:
            print(f"Error in user_input: {e}", flush=True)

    # endregion Connection and command routing

    # region Status display
    def QWidgetLabelColor(self, widget, textcolor, bgcolor=None):
        if bgcolor == None:
            label = "QLabel {color:%s}" % textcolor
            widget.setStyleSheet(label)
        else:
            label = "QLabel {color:%s;background:%s}" % (textcolor, bgcolor)
            widget.setStyleSheet(label)

    def QWidgetLabelStyle(self, widget, textcolor, bgcolor=None, fontsize=16, bold=True):
        current_style = widget.styleSheet().replace(" ","").lower()
        if "color:red" in current_style:
            return

        style = f"QLabel {{ color: {textcolor};"

        if textcolor == 'black':
            style += f" font-size: 14pt;"
            style += " font-weight: normal;"
        else:
            style += f" font-size: {fontsize}pt;"
            style += " font-weight: bold;" if bold else "font-weight: normal;"

        style += " }"

        widget.setStyleSheet(style)

    def FPLabelStyle(self, widget, textcolor, bgcolor=None, fontsize=20, bold=True):
        style = f"QLabel {{ color: {textcolor};"
        if bgcolor is not None:
            style += f" background: {bgcolor};"

        if textcolor == 'black':
            style += f" font-size: 20pt;"
            style += " font-weight: normal;"
        else:
            style += f" font-size: {fontsize}pt;"
            style += " font-weight: bold;" if bold else "font-weight: normal;"

        style += " }"

        widget.setStyleSheet(style)

    def show_status(self,dict_data):
        inst = dict_data.get('inst', 'None')
        process = dict_data.get('process', 'None')
        #message =dict_data.get('message','None')
        status = dict_data.get('status', 'error')
        subinst = dict_data.get('subinst', 'None')
        

        if process == 'Done':
            color_map = {'success': 'black','error': 'red', 'fail': 'black'}
        elif process in  ('ING', 'START'):
            color_map = {'success': 'orange','error': 'red', 'fail': 'black'}
        else:
            color_map = {}

        label_map = {
            'LAMP': self.ui.ok_status_lamp,
            'GFA': self.ui.ok_status_gfa,
            'ADC': self.ui.ok_status_adc,
            'FBP': self.ui.ok_status_fiber,
            'MTL' : self.ui.ok_status_metrology,
            'SPEC' : self.ui.ok_status_spectrograph
        }   
        label_map2 = {
            'LAMP': self.ui.ok_status_lamp_2,
            'GFA': self.ui.ok_status_gfa_2,
            'ADC': self.ui.ok_status_adc_2,
            'FBP': self.ui.ok_status_fiber_2,
            'MTL' : self.ui.ok_status_metrology_2,
            'SPEC' : self.ui.ok_status_spectrograph_2
        }   
        inst_map1 = {
            'LAMP': self.ui.label_status_lamp,
            'GFA': self.ui.label_status_gfa,
            'ADC': self.ui.label_status_adc,
            'FBP': self.ui.label_status_fiber,
            'MTL' : self.ui.label_status_metrology,
            'SPEC' : self.ui.label_status_spectrograph
        }
        inst_map2 = {
            'LAMP': self.ui.label_status_lamp_2,
            'GFA': self.ui.label_status_gfa_2,
            'ADC': self.ui.label_status_adc_2,
            'FBP': self.ui.label_status_fiber_2,
            'MTL' : self.ui.label_status_metrology_2,
            'SPEC' : self.ui.label_status_spectrograph_2
        }
        
        if inst in label_map and status in color_map:
            self.QWidgetLabelStyle(label_map[inst], color_map[status])
            self.QWidgetLabelStyle(label_map2[inst], color_map[status])
            self.QWidgetLabelStyle(inst_map1[inst], color_map[status])
            self.QWidgetLabelStyle(inst_map2[inst], color_map[status])

        if dict_data['inst'] == 'FBP':
            self._handle_fbp_state(dict_data)
        elif dict_data['inst'] == 'GFA':
            self._handle_gfa_state(inst, subinst, process)
        elif dict_data['inst'] == 'ADC':
            self._handle_adc_state(inst, process)
        elif dict_data['inst'] == 'LAMP':
            self._handle_lamp_state(inst, subinst, process)

    def _set_toggle_button(self, button, active):
        color = 'green' if active else 'black'
        button.setStyleSheet(f"color: {color}")
        button.setChecked(active)

    def _set_button_state(self, button, text, color, checked):
        button.setText(text)
        button.setStyleSheet(f"color: {color}")
        button.setChecked(checked)

    def reset_status(self):
        labels =[
            self.ui.ok_status_lamp,self.ui.ok_status_lamp_2,self.ui.label_status_lamp,self.ui.label_status_lamp_2,
            self.ui.ok_status_gfa,self.ui.ok_status_gfa_2,self.ui.label_status_gfa,self.ui.label_status_gfa_2,
            self.ui.ok_status_adc,self.ui.ok_status_adc_2,self.ui.label_status_adc,self.ui.label_status_adc_2,
            self.ui.ok_status_fiber,self.ui.ok_status_fiber_2,self.ui.label_status_fiber,self.ui.label_status_fiber_2,
            self.ui.ok_status_metrology,self.ui.ok_status_metrology_2,self.ui.label_status_metrology,self.ui.label_status_metrology_2,
            self.ui.ok_status_spectrograph,self.ui.ok_status_spectrograph_2,self.ui.label_status_spectrograph,self.ui.label_status_spectrograph_2,
            ]
        for label in labels:
            label.setStyleSheet(f"color: black")
        self.reset_fbp_error_labels()

    def set_inst_pos_state(self,dict_data):
        inst = dict_data.get('inst')
        if not inst:
            return

        state_map = {
            'ADC': ('adc_state', 'pos_state'),
    #        'FBP': ('fbp_state', 'pos_state'),
            'MTL': ('mtl_state', 'process'),
            'FIND': ('FIND_state', 'process'),
            'GFA': ('GFA_state', 'process'),
        }

        attr, key = state_map.get(inst, (None, None))
        if attr and key in dict_data:
            setattr(self, attr, dict_data[key])

    # endregion Status display

    # region FBP controls and state
    def update_fbp_error_labels(
        self,
        positions=None,
        *,
        normal_color='green',
        missing_color=None,
        error_axis=None
    ):
        if missing_color is None:
            missing_color = normal_color

        if positions in (None, 'None'):
            positions = {}

        if isinstance(positions, str):
            try:
                positions = json.loads(positions)
            except json.JSONDecodeError:
                self.logging('FBP position data has invalid format.', level='error')
                return

        if not isinstance(positions, dict):
            self.logging('FBP position data is not a dictionary.', level='error')
            return

        positions = dict(positions)

        if error_axis is not None:
            axis_key = str(error_axis)
            axis_data = positions.get(axis_key)
            if not isinstance(axis_data, dict):
                axis_data = {}
            axis_data['error'] = True
            positions[axis_key] = axis_data

        def is_error(value):
            if isinstance(value, str):
                return value.strip().lower() in ('true', '1', 'yes', 'error')
            return bool(value)

        positioner_axis_map = {
            'A1': ('1', '2'),
            'A2': ('3', '4'),
            'A3': ('5', '6'),
            'A4': ('7', '8'),
            'A5': ('9', '10'),
        }

        for positioner, axes in positioner_axis_map.items():
            label = getattr(self.ui, f'label_{positioner}', None)
            if label is None:
                continue

            axis_entries = [
                positions.get(axis)
                for axis in axes
                if isinstance(positions.get(axis), dict)
            ]

            has_error = any(
                is_error(axis_data.get('error', False))
                for axis_data in axis_entries
            )

            if has_error:
                self.FPLabelStyle(label, 'red')
            elif axis_entries and normal_color is not None:
                self.FPLabelStyle(label, normal_color)
            elif not axis_entries and missing_color is not None:
                self.FPLabelStyle(label, missing_color)

    def reset_fbp_error_labels(self):
        for label_name in ('A1', 'A2', 'A3', 'A4', 'A5'):
            label = getattr(self.ui, f'label_{label_name}', None)
            if label is not None:
                self.FPLabelStyle(label, 'black')

    def _handle_fbp_state(self, dict_data):
        if dict_data.get('inst') != 'FBP':
            return

        fbp_data = dict_data.get('data')
        if not isinstance(fbp_data, dict):
            fbp_data = {}

        func = dict_data.get('func', 'None')
        process = dict_data.get('process', 'None')
        status = dict_data.get('status', 'None')
        next_state = dict_data.get('fbp_state', 'None')

        if status == 'stopped':
            self.fbp_state = 'stop'
        elif next_state not in (None, 'None'):
            self.fbp_state = next_state

        if process in ('ING', 'START', 'Done') and self.fbp_state in ('assign', 'manual', 'stop'):
            self._set_button_state(self.ui.pushbtn_FBP_assign, 'FBP Assigned', 'green', True)
            self._set_button_state(self.ui.pushbtn_FBP_assign_2, 'FBP Assigned', 'green', True)
        elif process == 'Done' and self.fbp_state in ('zero', 'initial'):
            self._set_button_state(self.ui.pushbtn_FBP_assign, 'FBP Assign', 'black', False)
            self._set_button_state(self.ui.pushbtn_FBP_assign_2, 'FBP Assign', 'black', False)

        if process != 'Done':
            return

        positions = (
            fbp_data.get('final_positions')
            or fbp_data.get('stopped_positions')
        )

        if status in ('error', 'fail') and fbp_data.get('error_axis') is not None:
            self.update_fbp_error_labels(
                positions,
                normal_color=None,
                missing_color=None,
                error_axis=fbp_data.get('error_axis')
            )
            return

        if status in ('success', 'stopped') and (
            status == 'stopped' or func == 'fbpstop' or self.fbp_state == 'stop'
        ):
            self.update_fbp_error_labels(
                positions,
                normal_color='green',
                missing_color='green'
            )
            return

        if func == 'fbpmoveone' and status == 'success':
            positioner = fbp_data.get('positioner')
            if positioner:
                label = getattr(self.ui, f'label_{positioner}', None)
                if label is not None:
                    color = 'black' if self.fbp_state in ('zero', 'initial') else 'green'
                    self.FPLabelStyle(label, color)
            return

        if status == 'success' and self.fbp_state in ('zero', 'initial'):
            if positions:
                self.update_fbp_error_labels(
                    positions,
                    normal_color='black',
                    missing_color='black'
                )
            else:
                self.reset_fbp_error_labels()
            return

        if status == 'success' and self.fbp_state == 'assign':
            self.update_fbp_error_labels(
                positions,
                normal_color='green',
                missing_color='green'
            )
            return

        if positions:
            default_color = 'black' if self.fbp_state in ('zero', 'initial') else 'green'
            self.update_fbp_error_labels(
                positions,
                normal_color=default_color,
                missing_color=default_color
            )

    @asyncSlot()
    async def FBP_stop_button_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return

        await handle_fbp(f'fbpstop', self.ICS_client)
        self.logging(f'Sent Stop Positioners rotation.', level='send')

    @asyncSlot()
    async def FBP_lock_button_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return

        positioner_text = self.ui.lineEdit_FBP_lock.text().strip()

        if positioner_text:
            await handle_fbp(f'fbplock {positioner_text}', self.ICS_client)
            self.logging(f'Sent Lock Positioners {positioner_text}', level='send')
        else:
            await handle_fbp('fbplock', self.ICS_client)
            self.logging('Sent Unlock All Positioners', level='send')

    @asyncSlot()
    async def FBP_rotate_button_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return

        if not self.ui.lineEdit_FBP_number.text().strip() or not self.ui.lineEdit_FBP_angle.text().strip():
            self.logging('Insert positioner label you wnat to rotate and the desired angle.', level = 'error')
            return
        
        motor_alpha = self.ui.alpha_checkBox.isChecked()
        motor_beta = self.ui.beta_checkBox.isChecked()

        if not motor_alpha and not motor_beta:
            self.logging('Please check one motor you want to rotate.', level='error')
            return

        if motor_alpha and motor_beta:
            self.logging('Please check only one motor you want to rotate.', level='error')
            return

        motor_name = 'alpha' if motor_alpha else 'beta'
        max_angle = 360.0 if motor_alpha else 180.0
        angle = self.ui.lineEdit_FBP_angle.text().strip()

        try:
            angle_value = float(angle)
        except ValueError:
            self.logging('Insert a numeric FBP rotation angle.', level='error')
            return

        if not np.isfinite(angle_value):
            self.logging('Insert a finite FBP rotation angle.', level='error')
            return

        if angle_value < 0 or angle_value > max_angle:
            self.logging(f'{motor_name.capitalize()} angle must be between 0 and {max_angle:g} degrees.', level='error')
            return

        if self.fbp_state in ('zero', 'manual'):
            positioner_label = self.ui.lineEdit_FBP_number.text().strip()
            await handle_fbp(f'fbpmoveone {positioner_label} {motor_name} {angle}', self.ICS_client)
            self.logging(f'Sent Rotate Positioner {positioner_label} {motor_name} motor by {angle}.', level='send')
            self.ui.lineEdit_FBP_number.clear()
            self.ui.lineEdit_FBP_angle.clear()
        else:
            self.logging('Manual rotation of positioners is possible in zero positions. Please move positioners to zero position first.', level='error')

    @asyncSlot()
    async def FBP_assign_button_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return
        
        if self.fbp_state in ('zero','initial'):
            self.assign_state = not getattr(self,"assign_state",False)
            # sync two button
            self.ui.pushbtn_FBP_assign.setChecked(self.assign_state)
            self.ui.pushbtn_FBP_assign_2.setChecked(self.assign_state)
            await handle_fbp('fbpmoveall',self.ICS_client)
            self.logging('Sent Positioner assignment Starts.', level='send')
        else:
            self.logging('Some positioners are manually rotated. Plase re-rotate positioners to zero positions manually.', level='error')

    @asyncSlot()
    async def FBP_initial_button_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return

        if self.fbp_state == 'assign':
            await handle_fbp('fbpinitial', self.ICS_client)
            self.logging('Sent Move positioners to intial positions.', level='send')
        elif self.fbp_state == 'stop':
            await handle_fbp('fbpinitial_from_stop', self.ICS_client)
            self.logging('Sent Move positioners to intial positions.', level='send')
        elif self.fbp_state == 'initial':
            self.logging(f'Current positioner status is already {self.fbp_state}.', level='error')
        else:
            self.logging(f'This operation is only available when the positioners are in the assigned position. Current positioner status is {self.fbp_state}.', level='error')

    @asyncSlot()
    async def FBP_zero_button_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return

        if self.fbp_state == 'initial':
            await handle_fbp('fbpzero', self.ICS_client)
            self.logging('Sent Fiber moves to zero position.', level='send')
        elif self.fbp_state == 'manual':
            self.logging('Some positioners are manually rotated. Please re-rotate positioners to zero positions manually.', level='error')
            return
        elif self.fbp_state == 'zero':
            self.logging('Positioners are already zero postions.', level='error')
            return
        else:
            self.logging(f'Current positioner status is {self.fbp_state}. Please move positioners to initial positions first.', level='error')

    @asyncSlot()
    async def FBP_offset_button_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return

        if self.fbp_state not in (None,"assign"):
            self.logging('Fiber positioners are not assigned to targets. Click first assign button', level='error')
            return

        await handle_fbp('fbpoffset',self.ICS_client)
        self.logging('Sent Fiber offset starts.', level='send')

    @asyncSlot()
    async def FBP_Status_button_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return

        
        if not self.ui.lineEdit_FBP_number.text():
            self.logging('Insert Positioner Label to know status')
            return
        else:
            positioner_num = self.ui.lineEdit_FBP_number.text()
            await handle_fbp(f'fbpstatus {positioner_num}', self.ICS_client)
            self.logging(f'Sent Show positioner {positioner_num} status')

    # endregion FBP controls and state

    # region GFA guiding and pointing
    def _handle_gfa_state(self, inst, subinst, process):
        if inst != 'GFA':
            return

        if subinst == 'None':
            state = (process in ('ING','START'))
            self.guiding_state = state
            self._set_toggle_button(self.ui.pushbtn_Guiding, state)
            self._set_toggle_button(self.ui.pushbtn_Guiding_2, state)

    async def _handle_gfa_point_response(self, response_data, status):
        msg = response_data.get("message", "Unknown message")

        # 1. success: offset 값이 있어야 함
        if status == "success":
            required_keys = ("sepsec", "dra", "ddec", "new_ra", "new_dec")
            missing = [key for key in required_keys if key not in response_data]

            if missing:
                self.logging(
                    f"GFA POINT success response missing keys: {missing}",
                    status="error",
                    level="error",
                )
                await self.response_queue.put(response_data)
                return

            sepsec = round(response_data["sepsec"], 2)
            self.delta_ra = round(response_data["dra"], 2)
            self.delta_dec = round(response_data["ddec"], 2)

            self.ui.lineEdit_offset.setText(f"{sepsec}")
            self.ui.lineEdit_raoffset.setText(f"{self.delta_ra}")
            self.ui.lineEdit_decoffset.setText(f"{self.delta_dec}")

            self.new_ra = response_data["new_ra"]
            self.new_dec = response_data["new_dec"]

            await self.response_queue.put(response_data)
            return

        # 2. fail: 작업은 끝났지만 조건 미달
        if status == "fail":

            # 이전에 남아 있던 offset 값이 사용되지 않도록 초기화 권장
            self.delta_ra = None
            self.delta_dec = None
            self.new_ra = None
            self.new_dec = None

            self.ui.lineEdit_offset.clear()
            self.ui.lineEdit_raoffset.clear()
            self.ui.lineEdit_decoffset.clear()

            await self.response_queue.put(response_data)
            return

        # 3. error: 실제 오류
        if status == "error":
            self.logging(
                f"GFA POINT error: {msg}",
                status="error",
                level="error",
            )

            self.delta_ra = None
            self.delta_dec = None
            self.new_ra = None
            self.new_dec = None

            self.ui.lineEdit_offset.clear()
            self.ui.lineEdit_raoffset.clear()
            self.ui.lineEdit_decoffset.clear()

            await self.response_queue.put(response_data)
            return

        # 4. 알 수 없는 status
        self.logging(
            f"GFA POINT returned unknown status '{status}': {msg}",
            status="fail",
            level="warning",
        )
        await self.response_queue.put(response_data)

    @asyncSlot()
    async def GFArun_button_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return
        if not self.ui.lineEdit_GFA_exptime.text():
            self.ui.lineEdit_GFA_exptime.setText('5')      # Default guiding exposure time : 5 sec

        if not self.ui.lineEdit_GFA_cam.text():
            self.ui.lineEdit_GFA_cam.setText('0')

        if not self.ui.lineEdit_GFA_expnum.text():
            self.ui.lineEdit_GFA_expnum.setText('1')

        self.gfaexpt = float(self.ui.lineEdit_GFA_exptime.text())
        self.gfacam = int(self.ui.lineEdit_GFA_cam.text())
        self.gfaexpnum = int(self.ui.lineEdit_GFA_expnum.text())

#        gfasave=self.ui.gfa_checkBox.isChecked()

        await handle_gfa(f'gfagrab {self.gfacam} {self.gfaexpt} {self.gfaexpnum}',self.ICS_client)
        if self.gfacam == 0:
            self.logging(f'Sent Expose all GFA cameras for {self.gfaexpt} seconds.', level='send')
        else:
            self.logging(f'Sent Expose GFA camera {self.gfacam} for {self.gfaexpt} seconds.', level='send')

    @asyncSlot()
    async def Guiding_button_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return

        if not self.ra or not self.dec:
           self.logging(f'Please load Tile or slew telescope.',level='error')
           return

        if not self.ui.lineEdit_GFA_exptime.text():
            self.ui.lineEdit_GFA_exptime.setText('5')      # Default guiding exposure time : 5 sec

        if not self.ui.lineEdit_GFA_expnum.text():
            self.ui.lineEdit_GFA_expnum.setText('1')

        self.gfaexpt = float(self.ui.lineEdit_GFA_exptime.text())
        self.gfaexpnum = int(self.ui.lineEdit_GFA_expnum.text())

        self.guiding_state = not getattr(self,"guiding_state",False)

        # sync two button
        self.ui.pushbtn_Guiding.setChecked(self.guiding_state)
        self.ui.pushbtn_Guiding_2.setChecked(self.guiding_state)

        # Set colors
        style_on = "color: green; font-weight:900;"
        style_off = "color: black;"
        style = style_on if self.guiding_state else style_off
        self.ui.pushbtn_Guiding.setStyleSheet(style)
        self.ui.pushbtn_Guiding_2.setStyleSheet(style)

        # Command and log
        gfasave=self.ui.gfa_checkBox.isChecked()
        if self.guiding_state:
            if not gfasave:
                await handle_script(f'autoguide {self.gfaexpt} {self.gfaexpnum} False', scriptrun=self.scriptrun, logging=self.logging)
                self.logging(f'Sent Autoguiding Start. Exposure time is {self.gfaexpt}.', level='send')
            else:
                await handle_script(f'autoguide {self.gfaexpt} {self.gfaexpnum} True', scriptrun=self.scriptrun,logging=self.logging)
        else:
            await handle_script('autoguidestop', scriptrun=self.scriptrun,logging=self.logging)
            self.logging('Sent Autoguiding Stop', level='send')

    @asyncSlot()
    async def GFA_set_button_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return

        if not self.ui.lineEdit_GFA_exptime.text():
            self.ui.lineEdit_GFA_exptime.setText('5')

        self.gfaexpt = float(self.ui.lineEdit_GFA_exptime.text())
        self.logging(f'Set GFA exposure time to {self.gfaexpt}', level='send')
        self.scriptrun.GFA_set(self.gfaexpt)

    @asyncSlot()
    async def caloffset_button_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return

        if not self.ui.lineEdit_GFA_exptime.text():
            self.ui.lineEdit_GFA_exptime.setText('5')      # Default guiding exposure time : 5 sec

        if not self.ui.lineEdit_GFA_expnum.text():
            self.ui.lineEdit_GFA_expnum.setText('1')

        self.gfaexpt = float(self.ui.lineEdit_GFA_exptime.text())
        self.gfaexpnum = int(self.ui.lineEdit_GFA_expnum.text())


        if not self.ra or not self.dec:
           self.logging(f'Please load Tile or slew telescope.',level='error')
           return
       
        gfasave = self.ui.gfa_checkBox.isChecked()
        await handle_gfa(f'caloffset {self.gfaexpt} {self.gfaexpnum} {gfasave} {self.ra} {self.dec}',self.ICS_client)

    def format_decimal(self,x):
        from decimal import Decimal
        x = Decimal(str(x))
        sign = "-" if x < 0 else ""
        value = abs(x)
        return f"{sign}{int(value * 100):04d}"

    @asyncSlot()
    async def pointing_button_clicked(self):

        ### Apply offset value for telescope offset ###
    #    self.delta_ra = 0.34
    #    self.delta_dec = -1.23
    #    self.logging(f'Apply Offsets in (RA, DEC) = ({self.delta_ra}, {self.delta_dec})',level='normal')
    #    xx = self.format_decimal(self.delta_ra)
    #    msg = f'stepra {xx}'
    #    result = await self.send_telcom_command(msg)
    #    print('\033[94m' + '[ICS] received: ', result.decode() + '\033[0m', flush=True)
    #    self.logging(f'RA offset {self.delta_ra} finished', level='receive')
    #    await asyncio.sleep(1)
    #    yy = self.format_decimal(self.delta_dec)
    #    msg = f'stepdec {yy}'
    #    result = await self.send_telcom_command(msg)
    #    print('\033[94m' + '[ICS] received: ', result.decode() + '\033[0m', flush=True)
    #    self.logging(f'DEC offset {self.delta_dec} finished', level='receive')

    ### Use  New pointing coordinate for telescope offset ###
        self.logging(f'Applied Offsets {self.delta_ra}, {self.delta_dec}. New (RA,DEC)=({self.new_ra},{self.new_dec})',level='normal')
        self.logging(f'Slew Telescope to (RA,DEC)=({self.new_ra},{self.new_dec})',level='send')
        messagetcs = 'KSPEC>TC ' + 'tmradec ' + self.new_ra +' '+ self.new_dec
        await self.send_udp_message(messagetcs)

    # endregion GFA guiding and pointing

    # region ADC controls
    def _handle_adc_state(self, inst, process):
        if inst != 'ADC':
            return

        state = (process == 'ING')
        self.adcadjusting_state = state
        self._set_toggle_button(self.ui.pushbtn_ADCadjust, state)
        self._set_toggle_button(self.ui.pushbtn_ADCadjust_2, state)

    @asyncSlot()
    async def adcconnect_button_clicked(self):
        if not self.check_connection():
            return

        await handle_adc('adcconnect',self.ICS_client)

    @asyncSlot()
    async def ADCadjust_button_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return

        if self.ra is None or self.dec is None:
            self.logging('Please slew telescope to specific sky position or load sequence file',level='error')
            return


        self.adcadjusting_state = not getattr(self,"adcadjusting_state",False)

        # sync two button
        self.ui.pushbtn_ADCadjust.setChecked(self.adcadjusting_state)
        self.ui.pushbtn_ADCadjust_2.setChecked(self.adcadjusting_state)

        style_on = "color: green; font-weight:900;"
        style_off = "color: black;"
        style = style_on if self.adcadjusting_state else style_off
        self.ui.pushbtn_ADCadjust.setStyleSheet(style)
        self.ui.pushbtn_ADCadjust_2.setStyleSheet(style)

        if self.adcadjusting_state:
#            self.ui.pushbtn_ADCadjust.setStyleSheet("color: green; font-weight:900;")
#            self.ra='20:34:43.2'
#            self.dec='-32:34:56.4'
            await handle_adc(f'adcadjust {self.ra} {self.dec}', self.ICS_client)
            self.logging(f'Sent ADC adjusting for ({self.ra}, {self.dec}) Start.', level='send')
        else:
            self.ui.pushbtn_ADCadjust.setStyleSheet("color: black;")
            await handle_adc('adcstop',self.ICS_client)
            self.logging('Sent ADC adjusting Stop', level='send')

    def rotate_mode(self):
        chk1=self.ui.adc_checkBox1.isChecked()
        chk2=self.ui.adc_checkBox2.isChecked()
        chk3=self.ui.adc_checkBox_corotate.isChecked()

        if chk1 and chk2 and chk3:
            cmd = 'adccorotate'
        elif chk1 and chk2:
            cmd = 'adcctrotate'
        elif chk1 and not chk3:
            cmd = 'adcrotate1'
        elif chk2 and not chk3:
            cmd = 'adcrotate2'
        else:
            self.logging('Wrong checkbox. Check right ADC lens and rotation direction.', level='error')
            return

        return cmd

    @asyncSlot()
    async def adcrotate_button_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return

        if not self.ui.lineEdit_adc_counts.text():
            self.ui.lineEdit_adc_counts.setText('0')

        if not self.ui.lineEdit_adc_velocity.text():
            self.ui.lineEdit_adc_velocity.setText('1')

        self.adc_count = int(self.ui.lineEdit_adc_counts.text())
        self.adc_velocity = self.ui.lineEdit_adc_velocity.text()

        adccmd=self.rotate_mode()

        if adccmd == None:
            return
        else:
            fcmd = adccmd + ' ' + str(self.adc_count) + ' ' + str(self.adc_velocity)
            self.logging(f'Sent ADC {fcmd}', level='send')
            await handle_adc(fcmd, self.ICS_client)

    @asyncSlot()
    async def adcpark_button_clicked(self):
        if not self.check_connection():
            return

#        if not self.check_syscheck():
#            return

        self.logging(f'Sent ADC adcpark', level='send')
        await handle_adc('adcpark', self.ICS_client)

    @asyncSlot()
    async def adchome_button_clicked(self):
        if not self.check_connection():
            return

#        if not self.check_syscheck():
#            return

        if not self.ui.lineEdit_adc_velocity.text():
            self.ui.lineEdit_adc_velocity.setText('2')

        self.adc_velocity = self.ui.lineEdit_adc_velocity.text()

        self.logging(f'Sent ADC adchome', level='send')
        await handle_adc(f'adchome {self.adc_velocity}', self.ICS_client)

    @asyncSlot()
    async def adczero_button_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return

        if not self.ui.lineEdit_adc_velocity.text():
            self.ui.lineEdit_adc_velocity.setText('2')

        self.adc_velocity = self.ui.lineEdit_adc_velocity.text()
        
        self.logging(f'Sent ADC adczero', level='send')
        await handle_adc(f'adczero {self.adc_velocity}', self.ICS_client)

    # endregion ADC controls

    # region MTL controls
    @asyncSlot()
    async def MTL_exp_button_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return

        if not self.ui.lineEdit_MTL_exptime.text():
            self.ui.lineEdit_MTL_exptime.setText('5')
            
        if not self.ui.lineEdit_MTL_file.text():
            self.ui.lineEdit_MTL_file.setText('test.fits')
            
        if not self.ui.lineEdit_MTL_expnum.text():
            self.ui.lineEdit_MTL_expnum.setText('1')

        self.mtlexp = float(self.ui.lineEdit_MTL_exptime.text())
        self.mtlfile = str(self.ui.lineEdit_MTL_file.text())
        self.nexposure = int(self.ui.lineEdit_MTL_expnum.text())
        self.logging(f'Sent MTL exposure', level='send')
        await handle_mtl(f'mtlexp {self.mtlexp} {self.nexposure} {self.mtlfile}', self.ICS_client)

    @asyncSlot()
    async def MTL_cal_button_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return

    #    if not self.ui.lineEdit_MTL_exptime.text():
    #        self.ui.lineEdit_MTL_exptime.setText('5')
            
        if not self.ui.lineEdit_MTL_file.text():
            self.ui.lineEdit_MTL_file.setText('test.fits')
            
    #    if not self.ui.lineEdit_MTL_expnum.text():
    #        self.ui.lineEdit_MTL_expnum.setText('1')

    #    self.mtlexp = float(self.ui.lineEdit_MTL_exptime.text())
        self.mtlfile = str(self.ui.lineEdit_MTL_file.text())
    #    self.nexposure = int(self.ui.lineEdit_MTL_expnum.text())

        self.logging(f'Sent MTL calculation', level='send')
        await handle_mtl(f'mtlcal {self.mtlfile}', self.ICS_client)

    @asyncSlot()
    async def MTL_set_button_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return

        if not self.ui.lineEdit_MTL_exptime.text():
            self.ui.lineEdit_MTL_exptime.setText('5')

        self.mtlexp = float(self.ui.lineEdit_MTL_exptime.text())
        self.mtlfile = str(self.ui.lineEdit_MTL_file.text())
        self.mtlnum = float(self.ui.lineEdit_MTL_expnum.text())
        self.logging(f'Set MTL exposure time to {self.mtlexp}', level='send')
        self.scriptrun.MTL_set(self.mtlexp, self.mtlnum, self.mtlfile)

    # endregion MTL controls

    # region LAMP controls
    def _handle_lamp_state(self, inst, subinst, process):
        if inst != 'LAMP':
            return

    # 서브 상태에 따라 제어
        def apply(sub, state_var, button, button2):
            state = (process == 'ING')
            setattr(self, state_var, state)
            self._set_toggle_button(button, state)
            self._set_toggle_button(button2, state)

        if subinst == 'FIDUCIAL':
            apply('FIDUCIAL', 'fiducial_state', self.ui.pushbtn_Fiducial, self.ui.pushbtn_Fiducial_2)
        elif subinst == 'ARC':
            apply('ARC', 'arc_state', self.ui.pushbtn_Arc, self.ui.pushbtn_Arc_2)
        elif subinst == 'FLAT':
            apply('FLAT', 'flat_state', self.ui.pushbtn_Flat, self.ui.pushbtn_Flat_2)

    @asyncSlot()
    async def _onoff_button_clicked(self, state_attr, btn1, btn2, command_on, command_off, label):
        if not self.check_connection():
            return

#        if not self.check_syscheck():
#            return
        # call state and convert
        state = not getattr(self, state_attr, False)
        setattr(self, state_attr, state)

        # sync two button
        btn1.setChecked(state)
        btn2.setChecked(state)

        # set style
        style_on = "color: green; font-weight:900;"
        style_off = "color: black;"
        style = style_on if state else style_off
        btn1.setStyleSheet(style)
        btn2.setStyleSheet(style)

        # command and logging
        command = command_on if state else command_off
        #if command in ('fiducialon', 'fiducialoff'):
        result = await handle_lamp(command, self.ICS_client)
        self.logging(f"Sent {label} {'ON' if state else 'OFF'}", level='send')
        self.logging(f"{label} {'ON' if result == 1 else 'OFF'}", level='receive')
       

    @asyncSlot()
    async def flat_button_clicked(self):
        if not self.check_connection():
            return

    #    if not self.check_syscheck():
    #        return

        await self._onoff_button_clicked(state_attr="flat_state", btn1=self.ui.pushbtn_Flat, btn2=self.ui.pushbtn_Flat_2,
        command_on="flaton",command_off="flatoff",label="Flat")

    @asyncSlot()
    async def arc_button_clicked(self):
        if not self.check_connection():
            return

    #    if not self.check_syscheck():
    #        return

        await self._onoff_button_clicked(state_attr="arc_state", btn1=self.ui.pushbtn_Arc, btn2=self.ui.pushbtn_Arc_2,
        command_on="arcon",command_off="arcoff",label="Arc")

    @asyncSlot()
    async def fiducial_button_clicked(self):
        if not self.check_connection():
            return

    #    if not self.check_syscheck():
    #        return

        await self._onoff_button_clicked(state_attr="fiducial_state", btn1=self.ui.pushbtn_Fiducial, btn2=self.ui.pushbtn_Fiducial_2,
        command_on="fiducialon",command_off="fiducialoff",label="Fiducial")

    # endregion LAMP controls

    # region Spectrograph controls
    @asyncSlot()
    async def exp_start_clicked(self):
        if not self.check_connection():
            return


        self.obstype = self.ui.obstype.currentText()
        self.expT = self.ui.lineEdit_exp_time_2.text()
        self.expnum = self.ui.lineEdit_n_exp_2.text()

        header=set_header_info(obsdate = self.dir_name, obstype = self.obstype, TileID = self.TileID, obsra = self.ra,
            obsdec = self.dec, exptime = self.expT, expnum = self.expnum, projID = self.project, fwhm=self.fwhm)

        if self.obstype == 'Bias':
            await handle_spec(f'getobj {self.expT} {self.expnum}',self.ICS_client, header)    #### Need to change for bias
        else:
            await handle_spec(f'getobj {self.expT} {self.expnum}',self.ICS_client, header)

        if self.object in (None, '', 'None'):
            self.object = self.TileID
        
        cmt = ''
    
        if self.obslog is None:
            self.logging('Observation log is not ready. Skipping log update.', level='warning')
            return

        try:
            await asyncio.to_thread(
                self.obslog.add_log,
                self.uttime,
                self.project,
                self.TileID,
                self.obstype,
                self.object,
                self.expT,
                self.expnum,
                cmt,
            )
            self.logging(self.obslog.message, level='receive')
        except Exception as e:
            self.logging(f'Observation log update failed: {e}', level='error')

    def show_spec(self, spec_response):
    #    self.fwhm=response_data['fwhm']
        spec_canvas = [self.canvas_B, self.canvas_R]

        ### Simulation Start ####
        with fits.open('/media/shyunc/DATA/KSpec/DATA/RAWDATA/20260304/26030210001.fits') as hdul:
            data=hdul[0].data

        self.S_zmin, self.S_zmax = zs.zscale(data)
        self.canvas_B.imshows(data[0][540:740,:],vmin=self.S_zmin,vmax=self.S_zmax,cmap='gray',origin='lower',aspect='auto')

        with fits.open('/media/shyunc/DATA/KSpec/DATA/RAWDATA/20260304/26030220001.fits') as hdul:
            data=hdul[0].data

        self.S_zmin, self.S_zmax = zs.zscale(data)
        self.canvas_R.imshows(data[0][540:740,:],vmin=self.S_zmin,vmax=self.S_zmax,cmap='gray',origin='lower',aspect='auto')

    # endregion Spectrograph controls

    # region Observation script workflow
    @asyncSlot()
    async def syscheck(self):
        if not self.check_connection():
            return

        self.logging('System check start. Initialize dependencies',level='normal')

        self.scriptrun.initialize_dependencies(self.ICS_client, self.send_udp_message, self.send_telcom_command,
            self.response_queue, self.GFA_response_queue, self.ADC_response_queue, self.SPEC_response_queue, self.show_status, self.dir_name)

        self.dependencies = True
        self.logging('Script dependencies delivered.',level='normal')        

        await handle_script('obsinitial',scriptrun=self.scriptrun)

        labels = [self.ui.label_status_gfa,self.ui.label_status_adc,self.ui.label_status_fiber,self.ui.label_status_metrology,
            self.ui.label_status_spectrograph,self.ui.label_status_lamp]

        for label in labels:
            style = label.styleSheet().lower()
            if "color: red" in style:
                self.logging('While system checking, unexpected Errors have occurred in some instruments.',level='error')
                return True
        
        self.fbp_state = 'zero'

        try:
            self.obslog = obslog(self.dir_name)
            self.scriptrun.obslog = self.obslog
            self.logging(self.obslog.message, level='normal')

        except Exception as e:
            self.obslog = None
            self.scriptrun.obslog = None
            self.logging(
                f'Observation log sheet setup failed: {e}',
                level='error'
            )

        self.logging('System check finished. All systems are OK.',level='normal')

    def sync_script_observation_context(self):
        tile_id = self.ui.lineEdit_TileID.text().strip() or self.TileID
        ra = self.ui.lineEdit_ra_1.text().strip() or self.ra
        dec = self.ui.lineEdit_dec_1.text().strip() or self.dec
        exp_time = self.ui.lineEdit_exp_time_1.text().strip() or self.expT
        obs_num = self.ui.lineEdit_n_exp_1.text().strip() or self.obsnum

        if not all([tile_id, ra, dec, exp_time, obs_num]):
            self.logging('Please load tile information.', level='error')
            return False

        self.TileID = tile_id
        self.ra = ra
        self.dec = dec
        self.expT = exp_time
        self.obsnum = obs_num

        self.scriptrun.configure_cordinate(
            self.project,
            self.obsdate,
            self.TileID,
            self.ra,
            self.dec,
            self.obsnum,
            self.expT,
            object_name=self.object,
        )
        self.scriptrun.fwhm = self.fwhm
        self.scriptrun.obslog = self.obslog
        return True

    @asyncSlot()
    async def run_obs_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return

        if not self.ui.lineEdit_ra_1.text() or not self.ui.lineEdit_dec_1.text():
            self.logging('Please load tile information.', level='error')
            return

        if not self.sync_script_observation_context():
            return

        await handle_script(f'runobs',scriptrun=self.scriptrun,logging=self.logging)

    @asyncSlot()
    async def take_calib(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return
#        await self.scriptrun.run_calib(self.ICS_client, self.send_udp_message, self.send_telcom_command, self.response_queue,
#                self.GFA_response_queue, self.ADC_response_queue, self.SPEC_response_queue, logging=self.logging)

        self.scriptrun.fwhm = self.fwhm
        self.scriptrun.obslog = self.obslog
        await handle_script(f'runcalib', scriptrun=self.scriptrun,logging=self.logging)
        self.logging('Sent Calibration Start', level='send')

    @asyncSlot()
    async def load_tile(self):
        self.ui.lineEdit_CProj.setText(f'{self.project}')
        self.ui.lineEdit_CTile.setText(f'{self.TileID}')
    #    self.logging('Sent Guide stars information to GFA',level='send')
    #    await self.ICS_client.send_message("GFA", self.guidemsg)
    #    await self.response_queue.get()
    #    await asyncio.sleep(2)

        self.logging('Sent Target information to MTL',level='send')
        await self.ICS_client.send_message("MTL", self.objmsg)
        await self.response_queue.get()
        await asyncio.sleep(2)

    #    self.logging('Sent Target information to FBP',level='send')
    #    await self.ICS_client.send_message("FBP", self.objmsg)
    #    await self.response_queue.get()
    #    await asyncio.sleep(2)

    #    self.logging('Sent Motion plan of alpha motor to FBP',level='send')
    #    await self.ICS_client.send_message("FBP", self.motionmsg1)
    #    await self.response_queue.get()
    #    await asyncio.sleep(2)

    #    self.logging('Sent Motion plan of beta motor to FBP',level='send')
    #    await self.ICS_client.send_message("FBP", self.motionmsg2)
    #    await self.response_queue.get()
    #    await asyncio.sleep(2)

        self.logging(f'All accessary files for observation of Tile ID {self.TileID} are successfully loaded', level='receive')
        await asyncio.sleep(2)

    def load_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self)

        if not file_path:
            return

        if file_path:
            with open(file_path,'r') as f:
                lines=f.readlines()

        header = lines[0].strip().split()
        tile_lines = lines[1:]


        dialog = SelectTile(header[:4], tile_lines, self)
        if dialog.exec() != QDialog.Accepted or not dialog.selected_values:
            return

        self.TileID = dialog.selected_values[0]
        self.obsnum = dialog.selected_values[2]
        self.expT = dialog.selected_values[3]
#            self.ra = dialog.selected_values[4]        # For commission
#            self.dec = dialog.selected_values[5]       # For commission

#        print(self.ra)

        sciobs=sciobscli()
        filename=os.path.basename(file_path)
        wild=filename.split('_')
        sciobs.project=wild[0]
        sciobs.obsdate=wild[-1].split('.')[0]
        self.project=wild[0]
        self.obsdate=wild[-1].split('.')[0]
        print(self.project)
        print(self.obsdate)
        print(self.TileID)
#        print(self.ra)
#        print(self.dec)


#        self.objmsg=sciobs.loadtile(self.TileID)   # For commission
#        self.ra, self.dec=self.convert_to_sexagesimal(self.ra,self.dec)    # For commission
#        self.scriptrun.configure_cordinate(self.project, self.obsdate, self.TileID, self.ra, self.dec, self.obsnum, self.expT)   # For commission
#        self.ui.lineEdit_TileID.setText(f'{self.TileID}')
#        self.ui.lineEdit_ra_1.setText(f'{self.ra}')
#        self.ui.lineEdit_dec_1.setText(f'{self.dec}')
#        self.ui.lineEdit_exp_time_1.setText(f'{self.expT}')
#        self.ui.lineEdit_n_exp_1.setText(f'{self.obsnum}')
   

    ### Real survey Observation ####    
        self.tilemsg,self.guidemsg,self.objmsg,self.motionmsg1,self.motionmsg2=sciobs.loadtile(self.TileID)
        self.ra, self.dec=self.convert_to_sexagesimal(sciobs.ra,sciobs.dec)

        self.scriptrun.configure_cordinate(
            self.project,
            self.obsdate,
            self.TileID,
            self.ra,
            self.dec,
            self.obsnum,
            self.expT,
            object_name=self.object,
        )

        self.ui.lineEdit_TileID.setText(f'{self.TileID}')
        self.ui.lineEdit_ra_1.setText(f'{self.ra}')
        self.ui.lineEdit_dec_1.setText(f'{self.dec}')
        self.ui.lineEdit_exp_time_1.setText(f'{self.expT}')
        self.ui.lineEdit_n_exp_1.setText(f'{self.obsnum}')

    def reload_img(self,filename):
        rawdir='/media/shyunc/DATA/KSpec/RAWDATA/'
        filepath=os.path.join(rawdir,filename)

        try:
            with fits.open(filepath) as hdul:
                data = hdul[0].data

            # Z-scale 계산
            self.zmin, self.zmax = zs.zscale(data)

            # 기존 캔버스 초기화
            self.canvas_B.imshows(
                data,
                vmin=self.zmin,
                vmax=self.zmax,
                cmap='gray',
                origin='lower'
             )

            self.canvas_R.imshows(
                data,
                vmin=self.zmin,
                vmax=self.zmax,
                cmap='gray',
                origin='lower'
             )

#            self.canvas.ax.axis('off')
#            self.canvas.draw()

            self.logging(f"Loaded image: {filename}",level='normal')
            self.logging(f"Loaded image: {filename}",level='normal')

        except Exception as e:
            print(f"[ERROR] Could not load image {filepath}: {e}")
            self.logging(f"Failed to load image: {e}",level='error')
            self.logging(f"Failed to load image: {e}",level='error')

    def convert_to_sexagesimal(self,ra_deg, dec_deg):
        """Converts RA and DEC from degrees to sexagesimal format."""
        ra = Angle(ra_deg, unit=u.degree)
        dec = Angle(dec_deg, unit=u.degree)

        ra_hms = ra.to_string(unit=u.hour, sep=':', precision=2, pad=True)
        dec_dms = dec.to_string(unit=u.degree, sep=':', alwayssign=True, precision=2)
        return ra_hms, dec_dms

    # endregion Observation script workflow

    # region Telescope controls
    @asyncSlot()
    async def slew_button_clicked(self):
        if not self.check_connection():
            return

        if not self.ui.lineEdit_ra_2.text() or not self.ui.lineEdit_dec_2.text():
            self.logging('Please insert RA and DEC coordinates in Single Mode tap.', level='error')
            return
        else:
            self.ra = self.ui.lineEdit_ra_2.text()
            self.dec = self.ui.lineEdit_dec_2.text()

        self.sync_queue_mode()

        messagetcs = 'KSPEC>TC ' + 'tmradec ' + self.ra +' '+ self.dec
        self.logging(f'Slew Telescope to RA={self.ra}, DEC={self.dec}.', level='send')
        print(f'Slew Telescope to RA={self.ra}, DEC={self.dec}.')
        await self.send_udp_message(messagetcs)

    # endregion Telescope controls


if __name__ == "__main__":
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow()
    window.show()
    
    with loop:
        loop.run_forever()
#    sys.exit(app.exec())
