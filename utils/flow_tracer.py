"""Flow Tracer - Context-aware execution flow diagnostics for RF Tactical Monitor

Provides detailed execution tracing with context filtering, timing, and pass/fail status.
"""

import time
import threading
from typing import Optional
from utils.logger import setup_logger


# Antenna recommendations by frequency band
ANTENNA_RECOMMENDATIONS = {
    "adsb": {
        "name": "1090",
        "frequency": "1090 MHz",
        "use_case": "ADS-B aircraft tracking"
    },
    "ism_433": {
        "name": "829 MHz",
        "frequency": "433 MHz",
        "use_case": "Sub-GHz ISM TX/RX (garage doors, key fobs)"
    },
    "ism_868": {
        "name": "878 MHz",
        "frequency": "868 MHz",
        "use_case": "EU-style ISM devices"
    },
    "cellular_lte": {
        "name": "GW.52",
        "frequency": "700-2700 MHz",
        "use_case": "Cellular / Wi-Fi scanning"
    },
    "wifi": {
        "name": "GW.52",
        "frequency": "2.4/5 GHz",
        "use_case": "Wi-Fi network scanning"
    },
    "vhf_uhf": {
        "name": "SRH789",
        "frequency": "144-440 MHz",
        "use_case": "VHF/UHF voice communications"
    },
    "fm_broadcast": {
        "name": "TI.96",
        "frequency": "88-108 MHz",
        "use_case": "FM radio / VHF demo"
    },
    "wideband": {
        "name": "SRHF10",
        "frequency": "25-1300 MHz",
        "use_case": "Wideband scanning"
    }
}


class FlowTracer:
    """Context-aware flow tracer for debugging signal processing pipelines."""
    
    def __init__(self):
        # Use the main rf_tactical logger so messages appear in GUI
        self._logger = setup_logger("rf_tactical")
        self._active_context = None
        self._indent_level = 0
        self._context_stack = []
        self._timers = {}
        self._lock = threading.Lock()
        
    def set_context(self, context: str):
        """Set the active context (e.g., 'ISM', 'ADS-B', 'WIFI')."""
        with self._lock:
            self._active_context = context.upper()
            self._indent_level = 0
            self._context_stack.clear()
            
    def get_context(self) -> Optional[str]:
        """Get the current active context."""
        return self._active_context
    
    def _should_log(self, context: str) -> bool:
        """Check if we should log for this context."""
        if self._active_context is None:
            return True  # Log everything if no context set
        return context.upper() == self._active_context
    
    def _format_message(self, context: str, message: str, symbol: str = "->") -> str:
        """Format a trace message with context and indentation."""
        indent = "  " * self._indent_level
        return f"[{context.upper()}] {indent}{symbol} {message}"
    
    def enter(self, context: str, function_name: str, **kwargs):
        """Log entry into a function."""
        if not self._should_log(context):
            return
            
        with self._lock:
            # Check antenna recommendation
            antenna_msg = ""
            if context.lower() in ANTENNA_RECOMMENDATIONS:
                antenna = ANTENNA_RECOMMENDATIONS[context.lower()]
                antenna_msg = f" [Recommended antenna: {antenna['name']} for {antenna['frequency']}]"
            
            params = ", ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
            msg = self._format_message(context, f"START: {function_name}({params}){antenna_msg}", ">")
            self._logger.info(msg)
            
            self._context_stack.append(function_name)
            self._indent_level += 1
            self._timers[function_name] = time.time()
    
    def step(self, context: str, message: str):
        """Log a step in the execution flow."""
        if not self._should_log(context):
            return
            
        with self._lock:
            msg = self._format_message(context, message, "->")
            self._logger.info(msg)
    
    def success(self, context: str, message: str):
        """Log a successful operation."""
        if not self._should_log(context):
            return
            
        with self._lock:
            msg = self._format_message(context, message, "[OK]")
            self._logger.info(msg)
    
    def fail(self, context: str, message: str):
        """Log a failed operation."""
        if not self._should_log(context):
            return
            
        with self._lock:
            msg = self._format_message(context, message, "[FAIL]")
            self._logger.error(msg)
    
    def warning(self, context: str, message: str):
        """Log a warning."""
        if not self._should_log(context):
            return
            
        with self._lock:
            msg = self._format_message(context, message, "[WARN]")
            self._logger.warning(msg)
    
    def exit(self, context: str, function_name: str, status: str = "SUCCESS"):
        """Log exit from a function."""
        if not self._should_log(context):
            return
            
        with self._lock:
            self._indent_level = max(0, self._indent_level - 1)
            
            # Calculate elapsed time
            elapsed_ms = 0.0
            if function_name in self._timers:
                elapsed_ms = (time.time() - self._timers[function_name]) * 1000
                del self._timers[function_name]
            
            symbol = "[OK]" if status == "SUCCESS" else "[FAIL]"
            msg = self._format_message(context, f"END: {function_name} [{status}, {elapsed_ms:.1f}ms]", symbol)
            
            if status == "SUCCESS":
                self._logger.info(msg)
            else:
                self._logger.error(msg)
            
            if self._context_stack and self._context_stack[-1] == function_name:
                self._context_stack.pop()
    
    def data(self, context: str, name: str, value: str):
        """Log a data value."""
        if not self._should_log(context):
            return
            
        with self._lock:
            msg = self._format_message(context, f"{name} = {value}", "[DATA]")
            self._logger.info(msg)
    
    def check_antenna(self, context: str, frequency_hz: float):
        """Check and log antenna recommendation for frequency."""
        if not self._should_log(context):
            return
        
        # Find best antenna for this frequency
        freq_mhz = frequency_hz / 1e6
        
        antenna = None
        if context.lower() in ANTENNA_RECOMMENDATIONS:
            antenna = ANTENNA_RECOMMENDATIONS[context.lower()]
        elif 1080 <= freq_mhz <= 1100:
            antenna = ANTENNA_RECOMMENDATIONS["adsb"]
        elif 400 <= freq_mhz <= 470:
            antenna = ANTENNA_RECOMMENDATIONS["ism_433"]
        elif 850 <= freq_mhz <= 950:
            antenna = ANTENNA_RECOMMENDATIONS["ism_868"]
        elif 700 <= freq_mhz <= 2700:
            antenna = ANTENNA_RECOMMENDATIONS["cellular_lte"]
        elif 88 <= freq_mhz <= 108:
            antenna = ANTENNA_RECOMMENDATIONS["fm_broadcast"]
        elif 144 <= freq_mhz <= 440:
            antenna = ANTENNA_RECOMMENDATIONS["vhf_uhf"]
        else:
            antenna = ANTENNA_RECOMMENDATIONS["wideband"]
        
        if antenna:
            msg = self._format_message(
                context,
                f"Antenna check: {freq_mhz:.3f} MHz -> Use '{antenna['name']}' ({antenna['use_case']})",
                "[ANT]"
            )
            self._logger.info(msg)


# Global flow tracer instance
_flow_tracer = None


def get_flow_tracer() -> FlowTracer:
    """Get the global flow tracer instance."""
    global _flow_tracer
    if _flow_tracer is None:
        _flow_tracer = FlowTracer()
    return _flow_tracer
