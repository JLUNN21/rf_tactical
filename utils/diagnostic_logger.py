"""Diagnostic Logger - Comprehensive system diagnostics for RF Tactical Monitor

Logs all signal flows, connections, and data paths to help identify issues quickly.
Log file is cleared on application close.
"""

import logging
import sys
from pathlib import Path
from datetime import datetime


class DiagnosticLogger:
    """Comprehensive diagnostic logging system."""
    
    def __init__(self, log_file="diagnostic.log"):
        self.log_file = Path(log_file)
        self.logger = logging.getLogger("DIAGNOSTIC")
        self.logger.setLevel(logging.DEBUG)
        
        # Clear any existing handlers
        self.logger.handlers.clear()
        
        # File handler - detailed diagnostics
        file_handler = logging.FileHandler(self.log_file, mode='w')
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        self.logger.addHandler(file_handler)
        
        # Console handler - important messages only
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter('[%(levelname)s] %(message)s')
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)
        
        self._log_startup()
    
    def _log_startup(self):
        """Log startup banner."""
        self.logger.info("=" * 80)
        self.logger.info("RF TACTICAL MONITOR - DIAGNOSTIC LOG")
        self.logger.info(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info("=" * 80)
    
    def log_connection(self, source, target, signal_name):
        """Log a signal connection."""
        self.logger.info(f"CONNECT: {source} -> {target} [{signal_name}]")
    
    def log_signal_emit(self, source, signal_name, data_summary=""):
        """Log a signal emission."""
        self.logger.debug(f"EMIT: {source}.{signal_name} {data_summary}")
    
    def log_signal_receive(self, target, signal_name, data_summary=""):
        """Log a signal reception."""
        self.logger.debug(f"RECV: {target}.{signal_name} {data_summary}")
    
    def log_data_flow(self, source, destination, data_type, data_summary=""):
        """Log data flowing through the system."""
        self.logger.debug(f"DATA: {source} -> {destination} [{data_type}] {data_summary}")
    
    def log_component_init(self, component_name, status="OK"):
        """Log component initialization."""
        self.logger.info(f"INIT: {component_name} [{status}]")
    
    def log_component_start(self, component_name):
        """Log component start."""
        self.logger.info(f"START: {component_name}")
    
    def log_component_stop(self, component_name):
        """Log component stop."""
        self.logger.info(f"STOP: {component_name}")
    
    def log_error(self, component_name, error_msg):
        """Log an error."""
        self.logger.error(f"ERROR: {component_name} - {error_msg}")
    
    def log_warning(self, component_name, warning_msg):
        """Log a warning."""
        self.logger.warning(f"WARN: {component_name} - {warning_msg}")
    
    def log_button_click(self, button_name, action):
        """Log button click."""
        self.logger.info(f"BUTTON: {button_name} -> {action}")
    
    def log_tab_change(self, from_tab, to_tab):
        """Log tab change."""
        self.logger.info(f"TAB: {from_tab} -> {to_tab}")
    
    def log_sdr_status(self, status, details=""):
        """Log SDR status change."""
        self.logger.info(f"SDR: {status} {details}")
    
    def log_waterfall_update(self, tab_name, data_range):
        """Log waterfall data update."""
        self.logger.debug(f"WATERFALL: {tab_name} range={data_range}")
    
    def log_signal_detection(self, freq_mhz, power_dbm, device_type=""):
        """Log signal detection."""
        self.logger.info(f"SIGNAL: {freq_mhz:.3f} MHz @ {power_dbm:.1f} dBm [{device_type}]")
    
    def log_decoder_update(self, decoder_name, data_summary):
        """Log decoder data update."""
        self.logger.debug(f"DECODER: {decoder_name} - {data_summary}")
    
    def shutdown(self):
        """Clean shutdown - clear log file."""
        self.logger.info("=" * 80)
        self.logger.info("DIAGNOSTIC LOG - SHUTDOWN")
        self.logger.info(f"Ended: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info("=" * 80)
        
        # Close handlers
        for handler in self.logger.handlers[:]:
            handler.close()
            self.logger.removeHandler(handler)
        
        # Clear log file
        try:
            if self.log_file.exists():
                self.log_file.unlink()
        except Exception:
            pass


# Global diagnostic logger instance
_diagnostic_logger = None


def get_diagnostic_logger():
    """Get the global diagnostic logger instance."""
    global _diagnostic_logger
    if _diagnostic_logger is None:
        _diagnostic_logger = DiagnosticLogger()
    return _diagnostic_logger


def shutdown_diagnostic_logger():
    """Shutdown and cleanup diagnostic logger."""
    global _diagnostic_logger
    if _diagnostic_logger is not None:
        _diagnostic_logger.shutdown()
        _diagnostic_logger = None
