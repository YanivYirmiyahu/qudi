# -*- coding: utf-8 -*-
"""
This module operates a confocal microscope based on a stepping hardware.

Qudi is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Qudi is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Qudi. If not, see <http://www.gnu.org/licenses/>.

Copyright (c) the Qudi Developers. See the COPYRIGHT.txt file at the
top-level directory of this distribution and at <https://github.com/Ulm-IQO/qudi/>
"""

from qtpy import QtCore
from collections import OrderedDict
from copy import copy
import time
import datetime
import numpy as np
import matplotlib as mpl
import matplotlib.pyplot as plt
from io import BytesIO

from logic.generic_logic import GenericLogic


# Todo make a confocal stepper History class for this logic as exists in confocal logic. This is neede for restarting and
# for back and forward movement in images

class ConfocalStepperLogic(GenericLogic):  # Todo connect to generic logic
    """
    This is the Logic class for confocal stepping.
    """
    _modclass = 'confocalstepperlogic'
    _modtype = 'logic'

    _connectors = {
        'confocalstepper1': 'ConfocalStepperInterface',
        'savelogic': 'SaveLogic',
        'confocalcounter': 'FiniteCounterInterface'
    }

    signal_stop_stepping = QtCore.Signal()

    # Todo: For steppers with hardware realtime info like res readout of attocubes clock synchronisation and readout needs to be written
    # Therefore a new interface (ConfocalReadInterface o.ä.) needs to be made

    # Todo: add connectors and QTCore Signals

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)

    def on_activate(self):
        """ Initialisation performed during activation of the module.
        """

        # counter for scan_image
        self._step_counter = 0
        self._scan_axes = "xz"
        self._inverted_scan = False
        self.stopRequested = False
        self.depth_scan_dir_is_xz = True
        self._steps_scan_line = 50

        # Todo: Add initialisation from _statusVariable

        # Connectors
        self._stepping_device = self.get_connector('confocalstepper1')
        self._counting_device = self.get_connector('confocalcounter')
        self._save_logic = self.get_connector('savelogic')

        self.axis = self.get_stepper_axes_use()
        self.step_amplitude = dict()
        self._step_freq = dict()
        self._axis_mode = dict()
        for i in self.axis:
            # Todo: Add error check here or in method else it tries to write non existing value into itself
            self.step_amplitude[i] = self.get_stepper_amplitude(i)
            self._step_freq[i] = self.get_stepper_frequency(i)
            # Todo: write method that enquires stepping device mode
            self._axis_mode[i] = self._stepping_device.get_axis_mode(i)

            # Todo add connectors
        # Sets connections between signals and functions
        self.signal_step_lines_next.connect(self._step_line, QtCore.Qt.QueuedConnection)
        self.signal_start_stepping.connect(self.start_stepper, QtCore.Qt.QueuedConnection)
        self.signal_continue_stepping.connect(self.continue_stepper, QtCore.Qt.QueuedConnection)

    def on_deactivate(self):
        """ Reverse steps of activation

        @return int: error code (0:OK, -1:error)
        """
        pass

    def set_clock_frequency(self, clock_frequency):
        """Sets the frequency of the clock

        @param int clock_frequency: desired frequency of the clock

        @return int: error code (0:OK, -1:error)
        """
        self._clock_frequency = int(clock_frequency)
        # checks if stepper is still running
        if self.getState() == 'locked':
            return -1
        else:
            return 0

    def set_stepper_frequency(self, axis, frequency):
        """
        Sets the stepping frequency for a specific axis to frequency

        :param axis: The axis for the desired frequency
        :param frequency: desired frequency

        :return int: error code (0:OK, -1:error)
        """
        self._step_freq[axis] = frequency

        # checks if stepper is still running
        if self.getState() == 'locked':
            return -1
        return self._stepping_device.set_step_freq(axis, frequency)

    def get_stepper_frequency(self, axis):
        freq = self._stepping_device.get_step_freq(axis)
        if freq == -1:
            self.log.warning("The Stepping device could not read out the frequency")
            return self._step_freq
        # Todo. The error handling in the methods in the stepper is not good yet and this needs to be adapted the moment
        # this is better
        self._step_freq = freq
        return freq

    def set_stepper_amplitude(self, axis, amplitude):
        """
        Sets the stepping amplitude for a specific axis to amplitude

        :param axis: The axis for the desired frequency
        :param amplitude: desired amplitude (V)

        :return int: error code (0:OK, -1:error)
        """
        self.step_amplitude[axis] = amplitude
        # checks if stepper is still running
        if self.getState() == 'locked':
            return -1
        return self._stepping_device.set_step_amplitude(axis, amplitude)

    def get_stepper_amplitude(self, axis):
        amp = self._stepping_device.get_step_amplitude(axis)
        if amp == -1:
            self.log.warning("The Stepping device could not read out the amplitude")
            return self.step_amplitude
        # Todo. The error handling in the methods in the stepper is not good yet and this needs to be adapted the moment
        # this is better
        self.step_amplitude = amp
        return amp

    def set_mode_stepping(self, axis):
        """Sets the mode of the stepping device to stepping

        :param axis: The axis for which the mode is to be set
        :return int: error code (0:OK, -1:error)
        """
        self._axis_mode[axis] = "stepping"
        return self._stepping_device.set_axis_mode(axis, "stepping")

    def set_mode_ground(self, axis):
        """Sets the mode of the stepping device to grounded

        :param axis: The axis for which the mode is to be set
        :return int: error code (0:OK, -1:error)
        """
        self._axis_mode[axis] = "ground"
        return self._stepping_device.set_axis_mode(axis, "ground")

    def _check_freq(self, axis):
        """ Checks if the frequency in te device is the same as set by the program
        If the frequencies are different the frequency in the device is changed to the set
        frequency

        @return int: error code (0:OK, -1:error)
        """
        freq = self._stepping_device.get_step_freq(axis)
        if freq != self._step_freq(axis):
            self.log.warning(
                "The device has different frequency of {} then the set frequency {}. "
                "The frequency will be changed to the set frequency".format(freq, self._step_freq))
            # checks if stepper is still running
            if self.getState() == 'locked':
                self.log.warning("The stepper is still running")
                return -1
            return self._stepping_device.set_step_freq(self, axis, self._step_freq)
        return 0

    def _check_amplitude(self, axis):
        """ Checks if the voltage in te device is the same as set by the program
        If the voltages are different the voltage in the device is changed to the set voltage

        @return int: error code (0:OK, -1:error)
        """
        amp = self._stepping_device.get_step_amplitude(axis)
        if amp != self.step_amplitude(axis):
            self.log.warning(
                "The device has different voltage of {} then the set voltage {}. "
                "The voltage will be changed to the set voltage".format(amp, self.step_amplitude))
            # checks if stepper is still running
            if self.getState() == 'locked':
                self.log.warning("The stepper is still running")
                return -1
            return self._stepping_device.set_step_amplitude(self, axis, self.step_amplitude)
        return 0

    def get_stepper_axes_use(self):
        """ Find out how the axes of the stepping device are named.

        @return list(str): list of axis dictionary

        Example:
          For 3D confocal microscopy in cartesian coordinates, ['x':1, 'y':2, 'z':3] is a sensible
          value.
          If you only care about the number of axes and not the assignment and names
          use get_stepper_axes
          On error, return an empty list.
        """
        return self._stepping_device.get_stepper_axes_use()

    ################################### Control Stepper ########################################

    def start_stepper(self):
        """Starts the scanning procedure

        @return int: error code (0:OK, -1:error)
        """
        # Todo: Do we need a lock for the stepper as well?
        self._step_counter = 0
        self.lock()

        # Todo: to be done when GUI is done
        # if self.initialize_image() < 0:
        #    self.unlock()
        #    return -1

        a, b = self._scan_axes.split()
        if a in self.axis.keys() and b in self.axis.keys():
            if self._inverted_scan:
                self._first_scan_axis = a
                self._second_scan_axis = b
            else:
                self._first_scan_axis = b
                self._second_scan_axis = a
        else:
            self.log.error(
                "One of the chosen axes {} are not defined for the stepper hardware.".format(
                    self._scan_axes))
            self.unlock()
            return -1

        # Check the parameters of the stepper device
        freq_status = self._check_freq(self._first_scan_axis)
        amp_status = self._check_amplitude(self._second_scan_axis)
        if freq_status < 0 or amp_status < 0:
            self.unlock()
            return -1
        freq_status = self._check_freq(self._first_scan_axis)
        amp_status = self._check_amplitude(self._second_scan_axis)
        if freq_status < 0 or amp_status < 0:
            self.unlock()
            return -1

        # initialize counting device
        self._counting_device.lock()
        clock_status = self._counting_device.set_up_finite_counter_clock(
            clock_frequency=self._step_freq(self._first_scan_axis))
        if clock_status < 0:
            self._counting_device.unlock()
            self.unlock()
            return -1

        # Todo: The connection to the GUI amount of samples needs to be made
        # maybe a value given by the function needs to be implemented here
        scanner_status = self._counting_device.set_up_finite_counter(self._steps_scan_line)
        if scanner_status < 0:
            self._counting_device.close_finite_counter_clock()
            self._counting_device.unlock()
            self.unlock()
            return -1

        # set the axis to stepping
        axis_status1 = self.set_mode_stepping(self._first_scan_axis)
        axis_status2 = self.set_mode_stepping(self._second_scan_axis)
        if axis_status1 < 0 or axis_status2 < 0:
            self.set_mode_ground(self._first_scan_axis)
            self.set_mode_ground(self._second_scan_axis)
            self.unlock()
            return -1

        self._stepping_device.lock()
        self.signal_step_lines_next.emit(True)

        return 0

    def stop_stepper(self):
        """"Stops the scan

        @return int: error code (0:OK, -1:error)
        """
        # Todo: Make sure attocube axis are set back to gnd if deemed sensible
        with self.threadlock:
            if self.getState() == 'locked':
                self.stopRequested = True
        self.signal_stop_stepping.emit()
        return 0

    def continue_stepper(self):
        """Continue the stepping procedure

        @return int: error code (0:OK, -1:error)
        """
        self.lock()
        # Check the parameters of the stepper device
        freq_status = self._check_freq(self._first_scan_axis)
        amp_status = self._check_amplitude(self._second_scan_axis)
        if freq_status < 0 or amp_status < 0:
            self.unlock()
            return -1
        freq_status = self._check_freq(self._first_scan_axis)
        amp_status = self._check_amplitude(self._second_scan_axis)
        if freq_status < 0 or amp_status < 0:
            self.unlock()
            return -1

        pass

    def move_to_position(self, x=None, y=None, z=None):
        """Moving the stepping device (approximately) to the desired new position from the GUI.

        @param int x: if defined, position in x-direction (steps)
        @param int y: if defined, position in y-direction (steps)
        @param int z: if defined, position in z-direction (steps)

        @return int: error code (0:OK, -1:error)
        """

        self.log.info("Movement of attocubes to an absolute position no possible for steppers.\n"
                      "The position moved to is the given of amount of steps, not a physical "
                      "given range away")
        # Check if freq and voltage are set as set in GUI

        if x is not None and int(x) != self._current_x:
            # check freq and amplitude
            status_freq = self._check_freq("x")
            status_amp = self._check_amplitude("x")
            if status_amp < 0:
                self.log.error("A stepping is not possible, as the amplitude in the system and "
                               "the amp. in the gui are different for the x axis.Please check")
                return -1
            if status_freq < 0:
                self.log.error("A stepping is not possible, as the frequency in the system and "
                               "the freq. in the gui are different for the x axis.Please check")
                return -1

            x = int(x)
            # check the direction of the movement
            out = True
            x_steps = x - self._current_x
            if x_steps < 0:
                out = False
            return_value = self._stepping_device.move_attocube("x", True, out, steps=abs(x_steps))
            self._current_x = x
            if return_value == -1:
                return return_value

        if y is not None and int(y) != self._current_y:
            # check freq and amplitude
            status_freq = self._check_freq("y")
            status_amp = self._check_amplitude("y")
            if status_amp < 0:
                self.log.error("A stepping is not possible, as the amplitude in the system and "
                               "the amp. in the gui are different for the y axis.Please check")
                return -1
            if status_freq < 0:
                self.log.error("A stepping is not possible, as the frequency in the system and "
                               "the freq. in the gui are different for the y axis.Please check")
                return -1

            y = int(y)
            # check the direction of the movement
            out = True
            y_steps = y - self._current_y
            if y_steps < 0:
                out = False
            return_value = self._stepping_device.move_attocube("y", True, out, steps=abs(y_steps))
            self._current_y = y
            if return_value == -1:
                return return_value

        if z is not None and int(z) != self._current_z:
            # check freq and amplitude
            status_freq = self._check_freq("z")
            status_amp = self._check_amplitude("z")
            if status_amp < 0:
                self.log.error("A stepping is not possible, as the amplitude in the system and "
                               "the amp. in the gui are different for the z axis.Please check")
                return -1
            if status_freq < 0:
                self.log.error("A stepping is not possible, as the frequency in the system and "
                               "the freq. in the gui are different for the z axis.Please check")
                return -1

            z = int(z)
            # check the direction of the movement
            out = True
            z_steps = z - self._current_z
            if z_steps < 0:
                out = False
            return_value = self._stepping_device.move_attocube("z", True, out, steps=abs(z_steps))
            self._current_z = z
            return return_value
        self.log.warning("No movement was defined or necessary")
        return 0

    def get_position(self):
        """ Get position from stepping device.

        @return list: with three entries x, y and z denoting the current
                      position in meters
        """
        pass
        # Todo this only works with position feedback hardware. Not sure if should be kept, as not possible for half the steppers

    def _step_line(self, direction):
        """Stepping a line

        @param bool direction: the direction in which the previous line was scanned

        @return bool: If true scan was in up direction, if false scan was in down direction
        """
        # Todo: Make sure how to implement the threadlocking here correctly.

        # Todo: Think about the question wether we actually step the same amount of steps as we
        # count or is we might be off by one, as we are notcounting when moving up on in "y"


        # If the stepping measurement is not running do nothing
        if self.getState() != 'locked':
            return

            # stop stepping
        if self.stopRequested:
            with self.threadlock:
                self.kill_counter()
                self.stopRequested = False
                self.unlock()
                self._stepping_device.unlock()
                # self.signal_xy_image_updated.emit()
                # self.signal_depth_image_updated.emit()

                # if self._zscan:
                #    self._depth_line_pos = self._scan_counter
                # else:
                #    self._xy_line_pos = self._scan_counter
                # add new history entry
                # new_history = ConfocalHistoryEntry(self)
                # new_history.snapshot(self)
                # self.history.append(new_history)
                # if len(self.history) > self.max_history_length:
                #    self.history.pop(0)
                # self.history_index = len(self.history) - 1
                return

        # move and count
        new_counts = self._step_and_count(self._first_scan_axis, direction,
                                          steps=self._steps_scan_line)
        if new_counts[0] == -1:
            self.stopRequested = True
            self.signal_step_lines_next.emit(direction)
            return

        self._step_counter += 1
        if not direction:  # flip the count direction
            new_counts = np.flipud(new_counts)
        direction = not direction  # invert direction

        # move on line up
        self._stepping_device.move_attocube(self._second_scan_axis, True, True, 1)

        self.signal_step_lines_next(direction)


        # Todo This needs to do the following things: scan a line with the given amount of steps and th

    def _step_and_count(self, axis, direction=True, steps=1):
        """

        @param str axis: Axis for which the stepping should take place
        @param bool direction: direction of stepping (up: True or down: False)
        @param int steps: amount of steps, default 1
        @return np.array: acquired data in counts/s or error value -1
        """
        if self._stepping_device.move_attocube(axis, True, direction, steps=steps) < 0:
            self.log.error("moving of attocube failed")
            return -1

        if self._counting_device.start_finite_counter() < 0:
            self.log.error("Starting the counter failed")
            return -1

        time.sleep(steps * self._step_freq(axis))  # wait till stepping finished for readout
        result = self._counting_device.get_fixed_counts()
        retval = 0
        a = self._counting_device.stop_finite_counter()
        if result[0] == [-1]:
            self.log.error("The readout of the counter failed")
            retval = -1
        elif result[1] != steps:
            self.log.error("A different amount of data than necessary was returned.\n "
                           "Received {} instead of {} bins with counts ".format(result[1], steps))
            retval = -1
        elif a < 0:
            retval = -1
            self.log.error("Stopping the counter failed")
        else:
            retval = result[0]

        return retval

    ##################################### Acquire Data ###########################################

    def _initalize_stepping(self):
        """"

        return
        """
        pass

    def kill_counter(self):
        """Closing the counting device.

        @return int: error code (0:OK, -1:error)
        """
        try:
            self._counting_device.close_finite_counter()
        except Exception as e:
            self.log.exception('Could not close the scanner.')
        try:
            self._counting_device.close_finite_counter_clock()
        except Exception as e:
            self.log.exception('Could not close the scanner clock.')
        try:
            self._counting_device.unlock()
        except Exception as e:
            self.log.exception('Could not unlock scanning device.')

        return 0

    ##################################### Handle Data ########################################

    def initialize_image(self):
        """Initalization of the image.

        @return int: error code (0:OK, -1:error)
        """
        pass

    def save_xy_data(self, colorscale_range=None, percentile_range=None):
        """ Save the current confocal xy data to file.

        Two files are created.  The first is the imagedata, which has a text-matrix of count values
        corresponding to the pixel matrix of the image.  Only count-values are saved here.

        The second file saves the full raw data with x, y, z, and counts at every pixel.

        A figure is also saved.

        @param: list colorscale_range (optional) The range [min, max] of the display colour scale
                    (for the figure)

        @param: list percentile_range (optional) The percentile range [min, max] of the color scale
        """
        # Todo Ask if it is possible to write only one save with options for which lines were scanned
        pass

    def draw_figure(self, data, image_extent, scan_axis=None, cbar_range=None,
                    percentile_range=None, crosshair_pos=None):
        """ Create a 2-D color map figure of the scan image for saving

        @param: array data: The NxM array of count values from a scan with NxM pixels.

        @param: list image_extent: The scan range in the form [hor_min, hor_max, ver_min, ver_max]

        @param: list axes: Names of the horizontal and vertical axes in the image

        @param: list cbar_range: (optional) [color_scale_min, color_scale_max].  If not supplied
                                    then a default of data_min to data_max will be used.

        @param: list percentile_range: (optional) Percentile range of the chosen cbar_range.

        @param: list crosshair_pos: (optional) crosshair position as [hor, vert] in the chosen
                                    image axes.

        @return: fig fig: a matplotlib figure object to be saved to file.
        """

        # Todo Probably the function from confocal logic, that already exists need to be chaned only slightly
        pass

    ##################################### Tilt correction ########################################


    @QtCore.Slot()
    def set_tilt_point1(self):
        """ Gets the first reference point for tilt correction."""
        pass
        self.point1 = np.array(self._scanning_device.get_scanner_position()[:3])
        self.signal_tilt_correction_update.emit()

    @QtCore.Slot()
    def set_tilt_point2(self):
        """ Gets the second reference point for tilt correction."""
        pass
        self.point2 = np.array(self._scanning_device.get_scanner_position()[:3])
        self.signal_tilt_correction_update.emit()

    @QtCore.Slot()
    def set_tilt_point3(self):
        """Gets the third reference point for tilt correction."""
        pass
        self.point3 = np.array(self._scanning_device.get_scanner_position()[:3])
        self.signal_tilt_correction_update.emit()

    @QtCore.Slot(bool)
    def set_tilt_correction(self, enabled):
        """ Set tilt correction in tilt interfuse.

            @param bool enabled: whether we want to use tilt correction
        """
        self._scanning_device.tiltcorrection = enabled
        self._scanning_device.tilt_reference_x = self._scanning_device.get_scanner_position()[
            0]
        self._scanning_device.tilt_reference_y = self._scanning_device.get_scanner_position()[
            1]
        self.signal_tilt_correction_active.emit(enabled)

    ##################################### Move through History ########################################

    def history_forward(self):
        """ Move forward in confocal image history.
        """
        pass
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self.history[self.history_index].restore(self)
            self.signal_xy_image_updated.emit()
            self.signal_depth_image_updated.emit()
            self.signal_tilt_correction_update.emit()
            self.signal_tilt_correction_active.emit(self._scanning_device.tiltcorrection)
            self._change_position('history')
            self.signal_change_position.emit('history')
            self.signal_history_event.emit()

    def history_back(self):
        """ Move backwards in confocal image history.
        """
        pass
        if self.history_index > 0:
            self.history_index -= 1
            self.history[self.history_index].restore(self)
            self.signal_xy_image_updated.emit()
            self.signal_depth_image_updated.emit()
            self.signal_tilt_correction_update.emit()
            self.signal_tilt_correction_active.emit(self._scanning_device.tiltcorrection)
            self._change_position('history')
            self.signal_change_position.emit('history')
            self.signal_history_event.emit()