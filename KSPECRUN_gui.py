import sys
import os
import asyncio

from PySide6.QtCore import *
from PySide6.QtWidgets import (
        QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget, QMessageBox, QSizePolicy, QFileDialog, QListWidget,QListWidgetItem,
        QDialog
        )
from PySide6.QtGui import QMouseEvent, QGuiApplication, QTextCursor
from ui_mainwindow import Ui_MainWindow
from qasync import QEventLoop, asyncSlot
from astropy.io import fits
from astropy.coordinates import Angle, SkyCoord
import astropy.units as u
import Lib.mkmessage as mkmsg
import Lib.zscale as zs
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
#from ENDO.ENDOcli import handle_endo
from MTL.mtlcli import handle_mtl
from LAMP.lampcli import handle_lamp
from SPECTRO.speccli import handle_spec
from TCS.tcscli import handle_telcom
from script.scriptcli import handle_script
from script.scriptcli import script
from SCIOBS.sciobscli import sciobscli


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
    def __init__(self):

        super(MainWindow, self).__init__()
        self.setWindowTitle("K-SPEC ICS")
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.scriptrun=script()
#        self.showMaximized()

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

        self.obstype = None

        self.msglog_path = None

        self.ra = None
        self.dec = None

        self.mtlexp = None

        ### Instrument position state & state ###
        self.adcadjusting_state = False
        self.fbp_state = False
        self.find_state = False
        self.mtl_state = False
        self.guiding_state = False
        self.arc_state = False
        self.flat_state = False
        self.fiducial_state = False
    


#Make timer (LT & UTC) 
        self.datetime = QDateTime.currentDateTime().toString()
        #self.lcd.display(datetime)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.timeout)
        self.setWindowTitle('KSPEC ICS')
        self.timer.start()


    ######### Button setting #####
        # Setting Initial observation
        self.ui.pushbtn_connect.setCheckable(True)
        self.ui.pushbtn_connect.clicked.connect(self.rabbitmq_connect)
        self.ui.pushbtn_observer.clicked.connect(self.save_observer)
        self.ui.pushbtn_directory.clicked.connect(self.set_directory)
        self.ui.pushbtn_syscheck.clicked.connect(self.syscheck)


        # GFA & Guiding
        self.ui.pushbtn_Guiding.setCheckable(True)
        self.ui.pushbtn_Guiding.clicked.connect(self.Guiding_button_clicked)
        self.ui.pushbtn_Guiding_2.setCheckable(True)
        self.ui.pushbtn_Guiding_2.clicked.connect(self.Guiding_button_clicked)

        self.ui.pushbtn_GFArun.clicked.connect(self.GFArun_button_clicked)
        self.ui.pushbtn_GFA_set.clicked.connect(self.GFA_set_button_clicked)


        # ADC adjust
        self.ui.pushbtn_ADCadjust.setCheckable(True)
        self.ui.pushbtn_ADCadjust.clicked.connect(self.ADCadjust_button_clicked)
        self.ui.pushbtn_ADCadjust_2.setCheckable(True)
        self.ui.pushbtn_ADCadjust_2.clicked.connect(self.ADCadjust_button_clicked)

        self.ui.pushbtn_adc_rotate.clicked.connect(self.adcrotate_button_clicked)
        self.ui.pushbtn_adc_park.clicked.connect(self.adcpark_button_clicked)
        self.ui.pushbtn_adc_home.clicked.connect(self.adchome_button_clicked)
        self.ui.pushbtn_adc_zero.clicked.connect(self.adczero_button_clicked)

        # Fiber assign
        self.ui.pushbtn_Fiber_assign.clicked.connect(self.Fiber_assign_button_clicked)
        self.ui.pushbtn_Fiber_assign_2.clicked.connect(self.Fiber_assign_button_clicked)

        self.ui.pushbtn_FBP_zero.clicked.connect(self.FBP_zero_button_clicked)
        self.ui.pushbtn_FBP_offset.clicked.connect(self.FBP_offset_button_clicked)


        # MTL 
        self.ui.pushbtn_MTL_exp.clicked.connect(self.MTL_exp_button_clicked)
    #    self.ui.pushbtn_MTL_exp_2.clicked.connect(self.MTL_exp_button_clicked)
    #    self.ui.pushbtn_MTL_exp_3.clicked.connect(self.MTL_exp_button_clicked)

        self.ui.pushbtn_MTL_cal.clicked.connect(self.MTL_cal_button_clicked)
        self.ui.pushbtn_MTL_set.clicked.connect(self.MTL_set_button_clicked)


        # Load Sequence
        self.ui.pushbtn_load_sequence.clicked.connect(self.load_file)
        self.ui.pushbtn_set_sequence.clicked.connect(self.load_tile)


        # Take Image
        self.ui.pushbtn_run_obs.clicked.connect(self.run_obs_clicked)
        self.ui.pushbtn_run_calib.clicked.connect(self.take_calib)

        self.ui.pushbtn_exp_start.clicked.connect(self.exp_start_clicked)

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


        # Focusing
        self.ui.pushbtn_dfp5.clicked.connect(self.dfp5_buttuon_clicked)
        self.ui.pushbtn_dfm5.clicked.connect(self.dfm5_buttuon_clicked)
        self.ui.pushbtn_dfp005.clicked.connect(self.dfp005_buttuon_clicked)
        self.ui.pushbtn_dfm005.clicked.connect(self.dfm005_buttuon_clicked)
        self.ui.pushbtn_fttgoto.clicked.connect(self.fttgoto_buttuon_clicked)

        # CLI command 
        self.ui.pushbtn_send_cmd.clicked.connect(self.user_input)

        # Observer Comment
        self.ui.pushbtn_send_comment_1.clicked.connect(self.comment1_clicked)
        self.ui.pushbtn_send_comment_2.clicked.connect(self.comment2_clicked)


        # System status button
        self.ui.pushbtn_reset1.clicked.connect(self.reset_status)
        self.ui.pushbtn_reset2.clicked.connect(self.reset_status)


    ######### Canvas setting #####
        self.canvas_B=MplCanvas(self,dpi=100,left=0.00,right=1.,bottom=0.0,top=1.)
        self.B_layout=QVBoxLayout(self.ui.frame_B)
        self.B_layout.addWidget(self.canvas_B)

        self.canvas_R=MplCanvas(self,dpi=100,left=0.00,right=1.,bottom=0.0,top=1.)
        self.R_layout=QVBoxLayout(self.ui.frame_R)
        self.R_layout.addWidget(self.canvas_R)

        self.canvas_F=MplCanvas(self,dpi=100,left=0.00,right=1.,bottom=0.0,top=1.)
        self.F_layout=QVBoxLayout(self.ui.frame_finder)
        self.F_layout.addWidget(self.canvas_F)


        self.canvas_G1=MplCanvas(self,dpi=100,left=0.0,right=1.,bottom=0.,top=1.)
        self.G1_layout=QVBoxLayout(self.ui.Guide1)
        self.G1_layout.addWidget(self.canvas_G1)

        self.canvas_G2=MplCanvas(self,dpi=100,left=0.0,right=1.,bottom=0.,top=1.)
        self.G2_layout=QVBoxLayout(self.ui.Guide2)
        self.G2_layout.addWidget(self.canvas_G2)

        self.canvas_G3=MplCanvas(self,dpi=100,left=0.0,right=1.,bottom=0.,top=1.)
        self.G3_layout=QVBoxLayout(self.ui.Guide3)
        self.G3_layout.addWidget(self.canvas_G3)

        self.canvas_G4=MplCanvas(self,dpi=100,left=0.0,right=1.,bottom=0.,top=1.)
        self.G4_layout=QVBoxLayout(self.ui.Guide4)
        self.G4_layout.addWidget(self.canvas_G4)

        self.canvas_G5=MplCanvas(self,dpi=100,left=0.0,right=1.,bottom=0.,top=1.)
        self.G5_layout=QVBoxLayout(self.ui.Guide5)
        self.G5_layout.addWidget(self.canvas_G5)

        self.canvas_G6=MplCanvas(self,dpi=100,left=0.0,right=1.,bottom=0.,top=1.)
        self.G6_layout=QVBoxLayout(self.ui.Guide6)
        self.G6_layout.addWidget(self.canvas_G6)


    def adjust_window_size_by_screen(self):
        screen = QGuiApplication.primaryScreen()
        geometry = screen.availableGeometry()

        # Window size
        screen_width = geometry.width()
        screen_height = geometry.height()

        window_width = int(screen_width * 0.5)
        window_height = int(screen_height * 0.5)

        self.resize(window_width, window_height)


    def logging(self,message,status: str='success', level: str='send', save: str=True):
        if isinstance(message,dict):
            message=json.dumps(message)

        color_map={
            "send": "green", "receive": "blue", "error": "red"
        }

        if status == "error":
            level = 'error'

        color = color_map.get(level,"black")

        self.uttime = QDateTime.currentDateTimeUtc().toString('hh:mm:ss')
        self.ui.log1.append(f'<span style="color:{color};">[{self.uttime}][ICS] {message}</span>')
        self.ui.log2.append(f'<span style="color:{color};">[{self.uttime}][ICS] {message}</span>')
        self.ui.log1.moveCursor(QTextCursor.End)
        self.ui.log2.moveCursor(QTextCursor.End)

        if save :
            with open(self.msglog_path,'a') as f:
                f.write(f'[{self.uttime}][ICS] {message}\n')

### Observation Set function ###
    def save_observer(self):
        self.observer=self.ui.lineEdit_observer.text()
        self.logging(f"Observer '{self.observer}' Saved",level='normal')

### Set Save directory ###
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


#### Calling Status #####
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

    def show_status(self,dict_data):
        inst = dict_data.get('inst', 'None')
        process = dict_data.get('process', 'None')
        message =dict_data.get('message','None')
        status = dict_data.get('status', 'fail')
        subinst = dict_data.get('subinst', 'None')

        if process == 'Done':
            color_map = {'success': 'black','error': 'red'}
        elif process in  ('ING', 'START'):
            color_map = {'success': 'green','error': 'red'}
        else:
            color_map = {}

        label_map = {
            'LAMP': self.ui.ok_status_lamp,
            'GFA': self.ui.ok_status_gfa,
            'ADC': self.ui.ok_status_adc,
            'FBP': self.ui.ok_status_fiber,
            'FINDER': self.ui.ok_status_finder,
            'MTL' : self.ui.ok_status_metrology,
            'SPEC' : self.ui.ok_status_spectrograph
        }   
        label_map2 = {
            'LAMP': self.ui.ok_status_lamp_2,
            'GFA': self.ui.ok_status_gfa_2,
            'ADC': self.ui.ok_status_adc_2,
            'FBP': self.ui.ok_status_fiber_2,
            'FINDER': self.ui.ok_status_finder_2,
            'MTL' : self.ui.ok_status_metrology_2,
            'SPEC' : self.ui.ok_status_spectrograph_2
        }   
        inst_map1 = {
            'LAMP': self.ui.label_status_lamp,
            'GFA': self.ui.label_status_gfa,
            'ADC': self.ui.label_status_adc,
            'FBP': self.ui.label_status_fiber,
            'FINDER': self.ui.label_status_finder,
            'MTL' : self.ui.label_status_metrology,
            'SPEC' : self.ui.label_status_spectrograph
        }
        inst_map2 = {
            'LAMP': self.ui.label_status_lamp_2,
            'GFA': self.ui.label_status_gfa_2,
            'ADC': self.ui.label_status_adc_2,
            'FBP': self.ui.label_status_fiber_2,
            'FINDER': self.ui.label_status_finder_2,
            'MTL' : self.ui.label_status_metrology_2,
            'SPEC' : self.ui.label_status_spectrograph_2
        }
        
        if inst in label_map and status in color_map:
            self.QWidgetLabelStyle(label_map[inst], color_map[status])
            self.QWidgetLabelStyle(label_map2[inst], color_map[status])
            self.QWidgetLabelStyle(inst_map1[inst], color_map[status])
            self.QWidgetLabelStyle(inst_map2[inst], color_map[status])

        self._handle_fbp_state(inst, process)
        self._handle_gfa_state(inst, process)
        self._handle_adc_state(inst, process)
        self._handle_lamp_state(inst, subinst, process)

    def _handle_fbp_state(self,inst,process):
        if inst != 'FBP':
            return

        if process in ('ING', 'Done') and self.fbp_state == 'assign':
            self._set_button_state(self.ui.pushbtn_Fiber_assign, 'FBP Assigned', 'green', True)
            self._set_button_state(self.ui.pushbtn_Fiber_assign_2, 'FBP Assigned', 'green', True)
        elif process == 'Done' and self.fbp_state == 'zero':
            self._set_button_state(self.ui.pushbtn_Fiber_assign, 'FBP Assign', 'black', False)
            self._set_button_state(self.ui.pushbtn_Fiber_assign_2, 'FBP Assign', 'black', False)

    def _handle_gfa_state(self, inst, process):
        if inst != 'GFA':
            return

        state = (process in ('ING','START'))
        self.guiding_state = state
        self._set_toggle_button(self.ui.pushbtn_Guiding, state)
        self._set_toggle_button(self.ui.pushbtn_Guiding_2, state)

    def _handle_adc_state(self, inst, process):
        if inst != 'ADC':
            return

        state = (process == 'ING')
        self.adcadjusting_state = state
        self._set_toggle_button(self.ui.pushbtn_ADCadjust, state)
        self._set_toggle_button(self.ui.pushbtn_ADCadjust_2, state)

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

        
    def _set_toggle_button(self, button, active):
        color = 'green' if active else 'black'
        button.setStyleSheet(f"color: {color}")
        button.setChecked(active)

    def _set_button_state(self, button, text, color, checked):
        button.setText(text)
        button.setStyleSheet(f"color: {color}")
        button.setChecked(checked)
    

        """
        if inst == 'FBP':
            if (process in ("ING", "Done")) and self.fbp_state == 'assign':
                self.ui.pushbtn_Fiber_assign.setStyleSheet(f"color: green")
                self.ui.pushbtn_Fiber_assign_2.setStyleSheet(f"color: green")
                self.ui.pushbtn_Fiber_assign.setText("FBP Assigned")
                self.ui.pushbtn_Fiber_assign_2.setText("FBP Assigned")
            if (process == "Done") and (self.fbp_state == 'zero'):
                self.ui.pushbtn_Fiber_assign.setStyleSheet(f"color: black")
                self.ui.pushbtn_Fiber_assign_2.setStyleSheet(f"color: black")
                self.ui.pushbtn_Fiber_assign.setText("FBP Assign")
                self.ui.pushbtn_Fiber_assign_2.setText("FBP Assign")

        if inst == 'GFA':
            if process == 'ING':
                self.guiding_state = True
                self.ui.pushbtn_Guiding.setStyleSheet(f"color: green")
                self.ui.pushbtn_Guiding.setChecked(True)
                self.ui.pushbtn_Guiding_2.setStyleSheet(f"color: green")
                self.ui.pushbtn_Guiding_2.setChecked(True)

            elif process == 'Done':
                self.guiding_state = False
                self.ui.pushbtn_Guiding.setStyleSheet(f"color: black")
                self.ui.pushbtn_Guiding.setChecked(False)
                self.ui.pushbtn_Guiding_2.setStyleSheet(f"color: black")
                self.ui.pushbtn_Guiding_2.setChecked(False)

        if inst == 'ADC':
            if process == 'ING':
                self.adcadjusting_state = True
                self.ui.pushbtn_ADCadjust.setStyleSheet(f"color: green")
                self.ui.pushbtn_ADCadjust.setChecked(True)
                self.ui.pushbtn_ADCadjust_2.setStyleSheet(f"color: green")
                self.ui.pushbtn_ADCadjust_2.setChecked(True)

            elif process == 'Done':
                self.adcadjusting_state = False
                self.ui.pushbtn_ADCadjust.setStyleSheet(f"color: black")
                self.ui.pushbtn_ADCadjust.setChecked(False)
                self.ui.pushbtn_ADCadjust_2.setStyleSheet(f"color: black")
                self.ui.pushbtn_ADCadjust_2.setChecked(False)

        if inst == 'LAMP':
            subinst = dict_data.get('subinst', 'None')
            if subinst == 'FIDUCIAL' and process == 'ING':
                self.fiducial_state = True
                self.ui.pushbtn_Fiducial.setStyleSheet(f"color: green")
                self.ui.pushbtn_Fiducial.setChecked(True)
                self.ui.pushbtn_Fiducial_2.setStyleSheet(f"color: green")
                self.ui.pushbtn_Fiducial_2.setChecked(True)

            elif subinst == 'FIDUCIAL' and process == 'Done':
                self.Fiducial_state = False
                self.ui.pushbtn_Fiducial.setStyleSheet(f"color: black")
                self.ui.pushbtn_Fiducial.setChecked(False)
                self.ui.pushbtn_Fiducial_2.setStyleSheet(f"color: black")
                self.ui.pushbtn_Fiducial_2.setChecked(False)

            if subinst == 'ARC' and process == 'ING':
                self.arc_state = True
                self.ui.pushbtn_Arc.setStyleSheet(f"color: green")
                self.ui.pushbtn_Arc.setChecked(True)
                self.ui.pushbtn_Arc_2.setStyleSheet(f"color: green")
                self.ui.pushbtn_Arc_2.setChecked(True)

            elif subinst == 'ARC' and process == 'Done':
                self.arc_state = False
                self.ui.pushbtn_Arc.setStyleSheet(f"color: black")
                self.ui.pushbtn_Arc.setChecked(False)
                self.ui.pushbtn_Arc_2.setStyleSheet(f"color: black")
                self.ui.pushbtn_Arc_2.setChecked(False)

            if subinst == 'FLAT' and process == 'ING':
                self.flat_state = True
                self.ui.pushbtn_Flat.setStyleSheet(f"color: green")
                self.ui.pushbtn_Flat.setChecked(True)
                self.ui.pushbtn_Flat_2.setStyleSheet(f"color: green")
                self.ui.pushbtn_Flat_2.setChecked(True)

            elif subinst == 'FLAT' and process == 'Done':
                self.flat_state = False
                self.ui.pushbtn_Flat.setStyleSheet(f"color: black")
                self.ui.pushbtn_Flat.setChecked(False)
                self.ui.pushbtn_Flat_2.setStyleSheet(f"color: black")
                self.ui.pushbtn_Flat_2.setChecked(False)
            """
            
    def reset_status(self):
        labels =[
            self.ui.ok_status_lamp,self.ui.ok_status_lamp_2,self.ui.label_status_lamp,self.ui.label_status_lamp_2,
            self.ui.ok_status_gfa,self.ui.ok_status_gfa_2,self.ui.label_status_gfa,self.ui.label_status_gfa_2,
            self.ui.ok_status_adc,self.ui.ok_status_adc_2,self.ui.label_status_adc,self.ui.label_status_adc_2,
            self.ui.ok_status_fiber,self.ui.ok_status_fiber_2,self.ui.label_status_fiber,self.ui.label_status_fiber_2,
            self.ui.ok_status_finder,self.ui.ok_status_finder_2,self.ui.label_status_finder,self.ui.label_status_finder_2,
            self.ui.ok_status_metrology,self.ui.ok_status_metrology_2,self.ui.label_status_metrology,self.ui.label_status_metrology_2,
            self.ui.ok_status_spectrograph,self.ui.ok_status_spectrograph_2,self.ui.label_status_spectrograph,self.ui.label_status_spectrograph_2,
            ]
        for label in labels:
            label.setStyleSheet(f"color: black")


#### Calling Instrument position state #####
    def set_inst_pos_state(self,dict_data):
        inst = dict_data.get('inst')
        if not inst:
            return

        state_map = {
            'ADC': ('adc_state', 'pos_state'),
            'FBP': ('fbp_state', 'pos_state'),
            'MTL': ('mtl_state', 'process'),
            'FIND': ('FIND_state', 'process'),
            'GFA': ('GFA_state', 'process'),
        }

        attr, key = state_map.get(inst, (None, None))
        if attr and key in dict_data:
            setattr(self, attr, dict_data[key])
        

### Observer's comment to message log ###
    def comment1_clicked(self):
        comment=self.ui.lineEdit_comment_1.text()
        self.logging(f"Observer comment '{comment}'.",level='comment')
        self.ui.lineEdit_comment_1.clear()

    def comment2_clicked(self):
        comment=self.ui.lineEdit_comment_2.text()
        self.logging(f"Observer comment '{comment}'.",level='comment')
        self.ui.lineEdit_comment_2.clear()


##### Main Functions corresponding to the GUI action #####

    # Focusing button
    @asyncSlot()
    async def dfp5_buttuon_clicked(self):
        foffset = 0.5
        messagetcs = f'KSPEC>TC dfocus {foffset}'
        await self.send_udp_message(messagetcs)

    @asyncSlot()
    async def dfm5_buttuon_clicked(self):
        foffset = -0.5
        messagetcs = f'KSPEC>TC dfocus {foffset}'
        await self.send_udp_message(messagetcs)

    @asyncSlot()
    async def dfp005_buttuon_clicked(self):
        foffset = 0.005
        messagetcs = f'KSPEC>TC dfocus {foffset}'
        await self.send_udp_message(messagetcs)

    @asyncSlot()
    async def dfm005_buttuon_clicked(self):
        foffset = -0.005
        messagetcs = f'KSPEC>TC dfocus {foffset}'
        await self.send_udp_message(messagetcs)

    @asyncSlot()
    async def fttgoto_buttuon_clicked(self):
        ftt_value = self.ui.lineEdit_fttvalue.text()
        messagetcs = f'KSPEC>TC fttgoto {ftt_value}'
        await self.send_udp_message(messagetcs)


    # Telescope slew by single button
    @asyncSlot()
    async def slew_button_clicked(self):

        if not self.ui.lineEdit_ra_2.text() or not self.ui.lineEdit_dec_2.text():
            self.logging('Please insert RA and DEC coordinates in Single Mode tap.', level='error')
            return
        else:
            self.ra = self.ui.lineEdit_ra_2.text()
            self.dec = self.ui.lineEdit_dec_2.text()

            messagetcs = 'KSPEC>TC ' + 'tmradec ' + self.ra +' '+ self.dec
            self.logging(f'Slew Telescope to RA={self.ra}, DEC={self.dec}.', level='send')
            print(f'Slew Telescope to RA={self.ra}, DEC={self.dec}.')
            await self.send_udp_message(messagetcs)

    # Exposure spectrograph from single mode
    @asyncSlot()
    async def exp_start_clicked(self):
        exp_time = self.ui.lineEdit_exp_time_2.text()
        exp_num = self.ui.lineEdit_n_exp_2.text()
        if exp_time.strip() or exp_num.strip():
            await handle_spec(f'getobj {exp_time} {exp_num}',self.ICS_client)
        else:
            self.logging(f"Please insert exposure time and number of exposure", level='error')
    #    


    @asyncSlot()
    async def _onoff_button_clicked(self, state_attr, btn1, btn2, command_on, command_off, label):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return
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
        await handle_lamp(command, self.ICS_client)
        self.logging(f"Sent {label} {'ON' if state else 'OFF'}", level='send')


    ## Fiber positionser ##
    @asyncSlot()
    async def Fiber_assign_button_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return
        
        if self.fbp_state not in (None,"zero"):
            self.logging('Fiber positioners are not in zero position. Click Fiber Zero button.', level='error')
            return

        self.assign_state = True 
        #not getattr(self,"assign_state",False)

        # sync two button
        self.ui.pushbtn_Fiber_assign.setChecked(self.assign_state)
        self.ui.pushbtn_Fiber_assign_2.setChecked(self.assign_state)

        # Set colors
        style_on = "color: green; font-weight:900;"
        style_off = "color: black;"
        style = style_on if self.assign_state else style_off
        self.ui.pushbtn_Fiber_assign.setStyleSheet(style)
        self.ui.pushbtn_Fiber_assign_2.setStyleSheet(style)

        if self.assign_state:
            await handle_fbp('fbpmove',self.ICS_client)
            self.logging('Sent Fiber assignment Starts.', level='send')

    @asyncSlot()
    async def FBP_zero_button_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return

        if self.fbp_state not in (None,"assign"):
            self.logging('Fiber positioners are already in zero position', level='error')
            return

        await handle_fbp('fbpzero',self.ICS_client)
        self.logging('Sent Fiber moves to zero position.', level='send')

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

    ## GFA ##
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

        self.gfaexpt = float(self.ui.lineEdit_GFA_exptime.text())
        self.gfacam = int(self.ui.lineEdit_GFA_cam.text())


        gfasave=self.ui.gfa_checkBox.isChecked()
        await handle_gfa(f'gfagrab {self.gfacam} {self.gfaexpt}',self.ICS_client)
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

        if not self.ui.lineEdit_GFA_exptime.text():
            self.ui.lineEdit_GFA_exptime.setText('5')      # Default guiding exposure time : 5 sec

        self.gfaexpt = float(self.ui.lineEdit_GFA_exptime.text())

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
                await handle_script(f'autoguide {self.gfaexpt} False', scriptrun=self.scriptrun)
                self.logging(f'Sent Autoguiding Start. Exposure time is {self.gfaexpt}.', level='send')
            else:
                print(f'tekjkerjek {gfasave}')
                await handle_script(f'autoguide {self.gfaexpt} True', scriptrun=self.scriptrun)
        else:
            await handle_script('autoguidestop', scriptrun=self.scriptrun)
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


    def show_guiding(self):
        cutimgpath='/media/shyunc/DATA/KSpec/KSPEC_ICS/GFA/kspec_gfa_controller/src/img/cutout/'
        guidenum=['1','2','3','4']
        G_canvas=[self.canvas_G1,self.canvas_G2,self.canvas_G3,self.canvas_G4]

        for i,can in enumerate(G_canvas):
            with fits.open(cutimgpath+'cutout_fluxmax_'+str(i+1)+'.fits') as hdul:
                data=hdul[0].data

            self.G_zmin, self.G_zmax = zs.zscale(data)
            can.imshows(data,vmin=self.G_zmin,vmax=self.G_zmax,cmap='gray',origin='lower')

    def show_spec(self, spec_response):
    #    self.fwhm=response_data['fwhm']
        spec_canvas = [self.canvas_B, self.canvas_R, self.canvas_F]

        for i,can in enumerate(spec_canvas):
            with fits.open(spec_response['filename']) as hdul:
                data=hdul[0].data

            self.S_zmin, self.S_zmax = zs.zscale(data)
            can.imshows(data,vmin=self.S_zmin,vmax=self.S_zmax,cmap='gray',origin='lower')



    ### ADC ###
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
#            self.ra='09:34:43.2'
#            self.dec='-31:34:56.4'
            await handle_adc(f'adcadjust {self.ra} {self.dec}', self.ICS_client)
            self.logging(f'Sent ADC adjusting for ({self.ra}, {self.dec}) Start.', level='send')
        else:
            self.ui.pushbtn_ADCadjust.setStyleSheet("color: black;")
            await handle_adc('adcstop',self.ICS_client)
            self.logging('Sent ADC adjusting Stop', level='send')

    @asyncSlot()
    async def adcrotate_button_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return
        if not self.ui.lineEdit_adc_counts.text():
            self.ui.lineEdit_adc_counts.setText('0')

        self.adc = int(self.ui.lineEdit_adc_counts.text())

        adccmd=self.rotate_mode()
        print(adccmd)
        if adccmd == None:
            return
        else:
            fcmd = adccmd + ' '+ str(self.adc)
            self.logging(f'Sent ADC {fcmd}', level='send')
            await handle_adc(fcmd, self.ICS_client)

    @asyncSlot()
    async def adcpark_button_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return
        self.logging(f'Sent ADC adcpark', level='send')
        await handle_adc('adcpark', self.ICS_client)

    @asyncSlot()
    async def adchome_button_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return
        self.logging(f'Sent ADC adchome', level='send')
        await handle_adc('adchome', self.ICS_client)

    @asyncSlot()
    async def adczero_button_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return
        self.logging(f'Sent ADC adczero', level='send')
        await handle_adc('adczero', self.ICS_client)


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


    ### MTL Button ###
    @asyncSlot()
    async def MTL_exp_button_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return

        if not self.ui.lineEdit_MTL_exptime.text():
            self.ui.lineEdit_MTL_exptime.setText('5')

        self.mtlexp = float(self.ui.lineEdit_MTL_exptime.text())
        self.mtlfile = str(self.ui.lineEdit_MTL_file.text())
        self.logging(f'Sent MTL exposure', level='send')
        await handle_mtl(f'mtlexp {self.mtlexp} {self.mtlfile}', self.ICS_client)

    @asyncSlot()
    async def MTL_cal_button_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return

        self.logging(f'Sent MTL calculation', level='send')
        await handle_mtl(f'mtlcal', self.ICS_client)

    @asyncSlot()
    async def MTL_set_button_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return

        if not self.ui.lineEdit_MTL_exptime.text():
            self.ui.lineEdit_MTL_exptime.setText('5')

        self.mtlexp = float(self.ui.lineEdit_MTL_exptime.text())
    #    self.mtlfile = str(self.ui.lineEdit_MTL_file.text())
        self.logging(f'Set MTL exposure time to {self.mtlexp}', level='send')
        self.scriptrun.MTL_set(self.mtlexp)
        

    ### Flat Button ###
    @asyncSlot()
    async def flat_button_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return

        await self._onoff_button_clicked(state_attr="flat_state", btn1=self.ui.pushbtn_Flat, btn2=self.ui.pushbtn_Flat_2,
        command_on="flaton",command_off="flatoff",label="Flat")


    ### Arc Button ###
    @asyncSlot()
    async def arc_button_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return

        await self._onoff_button_clicked(state_attr="arc_state", btn1=self.ui.pushbtn_Arc, btn2=self.ui.pushbtn_Arc_2,
        command_on="arcon",command_off="arcoff",label="Arc")

    ### Fiducial Button ###
    @asyncSlot()
    async def fiducial_button_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return

        await self._onoff_button_clicked(state_attr="fiducial_state", btn1=self.ui.pushbtn_Fiducial, btn2=self.ui.pushbtn_Fiducial_2,
        command_on="fiducialon",command_off="fiducialoff",label="Fiducial")


    @asyncSlot()
    async def load_tile(self):
        self.ui.lineEdit_CProj.setText(f'{self.project}')
        self.ui.lineEdit_CTile.setText(f'{self.select_tile}')
        self.logging('Sent Guide stars information to GFA',level='send')
        await self.ICS_client.send_message("GFA", self.guidemsg)
        await self.response_queue.get()
        await asyncio.sleep(2)

        self.logging('Sent Target information to MTL',level='send')
        await self.ICS_client.send_message("MTL", self.objmsg)
        await self.response_queue.get()
        await asyncio.sleep(2)

        self.logging('Sent Target information to FBP',level='send')
        await self.ICS_client.send_message("FBP", self.objmsg)
        await self.response_queue.get()
        await asyncio.sleep(2)

        self.logging('Sent Motion plan of alpha motor to FBP',level='send')
        await self.ICS_client.send_message("FBP", self.motionmsg1)
        await self.response_queue.get()
        await asyncio.sleep(2)

        self.logging('Sent Motion plan of beta motor to FBP',level='send')
        await self.ICS_client.send_message("FBP", self.motionmsg2)
        await self.response_queue.get()
        await asyncio.sleep(2)

        self.logging(f'All accessary files for observation of Tile ID {self.select_tile} are successfully loaded', level='receive')
        await asyncio.sleep(2)
#        self.show_status('GFA','success')
#        self.show_status('MTL','success')
#        self.show_status('FBP','success')



    #### Run observation script ####
    @asyncSlot()
    async def run_obs_clicked(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return


        await handle_script(f'runobs',scriptrun=self.scriptrun,logging=self.logging)
        
#        self.show_status('ADC','normal')
#        self.show_status('GFA','normal')
#        self.show_status('MTL','normal')
#        self.show_status('FBP','normal')
#        self.show_status('LAMP','normal')
#        self.show_status('SPEC','normal')


    @asyncSlot()
    async def take_image(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return
#        self.obstype1=self.ui.obstype_1
        self.ui.obstype_1.setCurrentText('Bias')
#        await handle_spec('getobj 3 1', self.ICS_client)
#        self.ui.log1.append("sent message to device 'SPEC'. message: Get 1 bias images.")
#        self.ui.log1.append("sent message to device 'SPEC'. message: Get 1 bias images.")
#        msg=await self.response_queue.get()
#        self.ui.log.appendPlainText(f"{msg['file']}")

#        filename=msg['file']

#        self.reload_img(filename)
        print(self.obstype)
        self.obstype=self.ui.obstype_1.currentText()

        print(self.obstype)


    @asyncSlot()
    async def take_calib(self):
        if not self.check_connection():
            return

        if not self.check_syscheck():
            return
#        await self.scriptrun.run_calib(self.ICS_client, self.send_udp_message, self.send_telcom_command, self.response_queue,
#                self.GFA_response_queue, self.ADC_response_queue, self.SPEC_response_queue, logging=self.logging)

        await handle_script(f'runcalib', scriptrun=self.scriptrun,logging=self.logging)
        self.logging('Sent Calibration Start', level='send')

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
        if dialog.exec() == QDialog.Accepted and dialog.selected_values:
            self.select_tile=dialog.selected_values[0]
            self.obsnum=dialog.selected_values[2]
            self.expT=dialog.selected_values[3]

        sciobs=sciobscli()
        filename=os.path.basename(file_path)
        wild=filename.split('_')
        sciobs.project=wild[0]
        sciobs.obsdate=wild[-1].split('.')[0]
        self.project=wild[0]
        self.obsdate=wild[-1].split('.')[0]
        self.tilemsg,self.guidemsg,self.objmsg,self.motionmsg1,self.motionmsg2=sciobs.loadtile(self.select_tile)
        self.ra, self.dec=self.convert_to_sexagesimal(sciobs.ra,sciobs.dec)

        self.scriptrun.configure_cordinate(self.project, self.obsdate, self.select_tile, self.ra, self.dec, self.obsnum, self.expT)

        self.ui.lineEdit_TileID.setText(f'{self.select_tile}')
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



###  Check instrument connection and initializing
    @asyncSlot()
    async def syscheck(self):
        if not self.check_connection():
            return

        self.logging('System check start. Initialize dependencies',level='normal')
        self.scriptrun.initialize_dependencies(self.ICS_client, self.send_udp_message, self.send_telcom_command,
            self.response_queue, self.GFA_response_queue, self.ADC_response_queue, self.SPEC_response_queue, self.show_status, self.dir_name)

        await handle_script('obsinitial',scriptrun=self.scriptrun)

        labels = [self.ui.label_status_gfa,self.ui.label_status_adc,self.ui.label_status_finder,self.ui.label_status_fiber,self.ui.label_status_metrology,
            self.ui.label_status_spectrograph,self.ui.label_status_lamp]

        for label in labels:
            style = label.styleSheet().lower()
            if "color: red" in style:
                self.logging('While system checking, unexpected Errors have occurred in some instruments.',level='error')
                return True

        self.logging('System check finished. All systems are OK.',level='normal')
        self.dependencies = True
#        self.logging('System check finished. All systems are OK.',level='normal')


### Functions related with RabbitMQ ###
    ### Connect RabbitMQ Server ###
    @asyncSlot()
    async def rabbitmq_connect(self):
        if self.msglog_path == None:
            self.logging("Obseveing directory was not set. Please insert directory.",level='error',save=False)
            self.ui.pushbtn_connect.setChecked(False)
            return
        else:
            if self.ui.pushbtn_connect.isChecked():
                self.ui.pushbtn_connect.setText('Connected')
                self.ui.pushbtn_connect.setStyleSheet('color: green;')

                print(f'Observer Name: {self.observer}')
            # Connect RabbitMQ
                with open('./Lib/KSPEC.ini', 'r') as f:
                    kspecinfo = json.load(f)

                self.ICS_client = AMQclass(
                    kspecinfo['RabbitMQ']['ip_addr'],
                    kspecinfo['RabbitMQ']['idname'],
                    kspecinfo['RabbitMQ']['pwd'],
                    'ICS', 'ics.ex'
                )

                react = await self.ICS_client.connect()
                self.logging(react,level='AMQ')
                react = await self.ICS_client.define_producer()
                self.logging(react,level='AMQ')


                await self.ICS_client.define_consumer('ICS',self.on_ics_message)
#               asyncio.create_task(self.wait_for_response())

            else:
                self.ui.pushbtn_connect.setText('Connect')
                self.ui.pushbtn_connect.setStyleSheet('color: black;')
                await self.ICS_client.disconnect()


    ### check connection to RabbitMQ Server and system  ###
    def check_connection(self):
        if not getattr(self,'ICS_client',False):
            self.logging("ICS_client is not connected to RabbitMQ server. Please click 'connect' button.", level='error')
            return False
        return True

    def check_syscheck(self):
        if not getattr(self,'dependencies', False):
            self.logging("Systems are not checked. Please click 'Sys check' button.", level='error')
            return False
        return True


    ### Waiting for response through RabbitMQ ###
    async def on_ics_message(self, message: IncomingMessage):
        async with message.process():
            try:
                response_data = json.loads(message.body)
                print(response_data)
                inst = response_data.get('inst', 'None')
                process = response_data.get('process', 'None')
                message = response_data.get('message','None')
                status = response_data.get('status', 'fail')
                self.set_inst_pos_state(response_data)
                self.show_status(response_data)
                
                if isinstance(message,dict):
                    message = json.dumps(message, indent=2)
                    print(f'\033[94m[ICS] received from {inst}: {message}\033[0m\n', flush=True)
                  #  self.logging(f'received from {inst}: {message}',level='receive')
                    self.logging(message, status, level='receive')
                else:
                    print(f'\033[94m[ICS] received from {inst}: {response_data["message"]}\033[0m\n', flush=True)
                  #  self.logging(f'received from {inst}: {response_data["message"]}',level='receive')
                    self.logging(message, status, level='receive')

                queue_map = {"GFA": self.GFA_response_queue, "ADC": self.ADC_response_queue, "SPEC": self.SPEC_response_queue}
                if inst in queue_map and process in ('ING', 'START'):
            #    if inst in queue_map and process in ('ING'):
                    await queue_map[inst].put(response_data)
                    if inst == 'GFA' and process == 'ING':
                        self.fwhm=response_data['fwhm']
                        print(f'ttttt {self.fwhm}')
                        self.ui.lineEdit_seeing.setText(f'{self.fwhm}')
                        self.show_guiding()
                elif inst == 'SPEC' and response_data['filename'] != 'None':
                    self.show_spec(response_data)
                    await self.response_queue.put(response_data)
                else:
                    print('put response_data to response_queue')      # To comment this out in real observation
                    await self.response_queue.put(response_data)
            except Exception as e:
                print(f"Error in wait_for_response: {e}", flush=True)
                self.logging(f"Error in wait_for_response: {e}", 'fail', level='error')


    ### Sending command to udp, telcom and rabbitmq ###
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
        return result

    async def send_command(self, category, message):
        """
        Sends a command using the respective handler.
        """
        handler_map = {
            "adc": handle_adc, "gfa": handle_gfa, "fbp": handle_fbp,
            "mtl": handle_mtl, "lamp": handle_lamp,
            "spec": handle_spec, "script": handle_script
        }
        if category in handler_map:
            await handler_map[category](message, self.ICS_client)
        else:
            print(f"Unknown command category: {category}",flush=True)

        self.ui.lineEdit_cmd.clear()
        self.ui.lineEdit_cmd_2.clear()


    ### User input command like CLI ###
    @asyncSlot()
    async def user_input(self):
        """
        Handles user input asynchronously, allowing immediate command sending.
        """
        try:
            sys.stdout.flush()
#                message = await asyncio.get_running_loop().run_in_executor(None, input, "Input command: ")
#                if message.lower() == "quit":
#                    print("Exiting user input mode.", flush=True)
#                    self.running = False
#                    break

            message=self.ui.lineEdit_cmd.text()
            cmd = message.split(" ")[0]
            category = self.find_category(cmd)
            print(f'Command Category is {category}', flush=True)

            if category:
                if category.lower() == 'tcs':
                    messagetcs = 'KSPEC>TC ' + message
                    await self.send_udp_message(messagetcs)
                elif category.lower() == 'telcom':
                    telcom_result = await self.send_telcom_command(message)
                    print('\033[94m' + '[ICS] received: ', telcom_result.decode() + '\033[0m', flush=True)
                    self.logging(f'<span style="color:green;">[ICS] received from {inst}: {message}</span>',level='receive')
                elif category.lower() == "script":
                    await handle_script(message, scriptrun=self.scriptrun)
                else:
                    await self.send_command(category, message)
            else:
                print("Invalid command. Please enter a valid command.\n", flush=True)
        except Exception as e:
            print(f"Error in user_input: {e}", flush=True)


    def load_command_list(self):
        return {
            "adc": ["adcstatus", "adcactivate", "adcadjust", "adcinit", "adcconnect", "adcdisconnect", "adchome", "adczero",
            "adcpoweroff", "adcrotate1", "adcrotate2", "adcstop", "adcpark", "adcrotateop", "adcrotatesame"],
            "gfa": ["gfastatus", "gfagrab", "gfaguidestop", "gfaguide", "fdgrab"],
            "fbp": ["fbpstatus", "fbpzero", "fbpmove", "fbpoffset"],
#            "endo": ["endoguide", "endotest", "endofocus", "endostop","endoexpset","endoclear","endostatus"],
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

            "telcom": ["getall", "getra", "getdec", "getha", "getel", "getaz", "getsecz", "mvstow", "mvelaz", "mvstop", "mvra", "mvdec", "track"],
            "utils": ["?","obsstatus","loadtile","setdir"],
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



#Close Event : to prevent to close the window easily
    def closeEvent(self, QCloseEvent):
        re = QMessageBox.question(self, "Close the program", "Are you sure you want to quit?",
                    QMessageBox.Yes|QMessageBox.No)

        if re == QMessageBox.Yes:
            QCloseEvent.accept()
        else:
            QCloseEvent.ignore() 

    def timeout(self):
        sender = self.sender()
        self.currentTime = QDateTime.currentDateTime().toString('yyyy.MM.dd, hh:mm:ss')
        self.currentutc = QDateTime.currentDateTimeUtc().toString('yyyy.MM.dd, hh:mm:ss')
        #print(currentTime)
        if id(sender) == id(self.timer):
            self.ui.lcd_lt.display(self.currentTime)
            self.ui.lcd_utc.display(self.currentutc)

#    def load_data(self, 

if __name__ == "__main__":
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow()
    window.show()
    
    with loop:
        loop.run_forever()
#    sys.exit(app.exec())
