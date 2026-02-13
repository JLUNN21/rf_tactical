"""Repetition Detector for grouping related RF transmissions.

Garage door remotes and similar devices typically send the same code
multiple times (3-5 repetitions). This module groups these repetitions
to identify unique button presses.
"""

import time
from typing import List, Dict, Optional
from collections import deque


class RepetitionDetector:
    """Detects and groups repeated signal transmissions."""
    
    def __init__(self, window_ms: float = 150, similarity_threshold: float = 0.8):
        """Initialize repetition detector.
        
        Args:
            window_ms: Time window in milliseconds to look for repetitions
            similarity_threshold: Pattern similarity threshold (0-1)
        """
        self.window_ms = window_ms
        self.window_s = window_ms / 1000.0
        self.similarity_threshold = similarity_threshold
        
        # Buffer of recent detections
        self.detection_buffer = deque(maxlen=20)
        
        # Grouped transmissions
        self.groups = []
        
    def add_detection(self, detection: Dict) -> Optional[Dict]:
        """Add a new detection and check for repetitions.
        
        Args:
            detection: Detection dictionary with:
                - timestamp: Detection time
                - pattern: Binary pattern string
                - frequency: Center frequency
                - power: Signal power
                - duration: Signal duration
                - pulses: Pulse information
                
        Returns:
            Grouped detection if repetitions found, None otherwise
        """
        current_time = time.time()
        
        # Add timestamp if not present
        if 'timestamp' not in detection:
            detection['timestamp'] = current_time
        
        # Add to buffer
        self.detection_buffer.append(detection)
        
        # Clean old detections outside window
        self._clean_old_detections(current_time)
        
        # Look for repetitions
        group = self._find_repetitions(detection)
        
        if group and group['repetition_count'] >= 2:
            return group
        
        return None
    
    def _clean_old_detections(self, current_time: float):
        """Remove detections older than the time window."""
        while self.detection_buffer:
            oldest = self.detection_buffer[0]
            if current_time - oldest['timestamp'] > self.window_s:
                self.detection_buffer.popleft()
            else:
                break
    
    def _find_repetitions(self, new_detection: Dict) -> Optional[Dict]:
        """Find repetitions of the new detection in the buffer.
        
        Args:
            new_detection: The detection to find repetitions of
            
        Returns:
            Grouped detection dictionary or None
        """
        if len(self.detection_buffer) < 2:
            return None
        
        # Get pattern from new detection
        new_pattern = new_detection.get('pattern', '')
        if not new_pattern:
            return None
        
        # Find similar patterns in buffer
        similar_detections = []
        
        for det in self.detection_buffer:
            pattern = det.get('pattern', '')
            if not pattern:
                continue
            
            # Calculate pattern similarity
            similarity = self._pattern_similarity(new_pattern, pattern)
            
            if similarity >= self.similarity_threshold:
                similar_detections.append(det)
        
        if len(similar_detections) < 2:
            return None
        
        # Create grouped detection
        return self._create_group(similar_detections)
    
    def _pattern_similarity(self, pattern1: str, pattern2: str) -> float:
        """Calculate similarity between two binary patterns.
        
        Uses Hamming distance normalized by length.
        
        Args:
            pattern1: First binary pattern string
            pattern2: Second binary pattern string
            
        Returns:
            Similarity score from 0 (completely different) to 1 (identical)
        """
        if not pattern1 or not pattern2:
            return 0.0
        
        # Handle different lengths by comparing up to shorter length
        min_len = min(len(pattern1), len(pattern2))
        max_len = max(len(pattern1), len(pattern2))
        
        if max_len == 0:
            return 0.0
        
        # Count matching bits
        matches = sum(1 for i in range(min_len) if pattern1[i] == pattern2[i])
        
        # Penalize length difference
        length_penalty = min_len / max_len
        
        # Calculate similarity
        similarity = (matches / min_len) * length_penalty
        
        return similarity
    
    def _create_group(self, detections: List[Dict]) -> Dict:
        """Create a grouped detection from similar detections.
        
        Args:
            detections: List of similar detections
            
        Returns:
            Grouped detection dictionary
        """
        # Sort by timestamp
        detections = sorted(detections, key=lambda d: d['timestamp'])
        
        # Calculate statistics
        first_time = detections[0]['timestamp']
        last_time = detections[-1]['timestamp']
        time_span_ms = (last_time - first_time) * 1000
        
        # Average power
        powers = [d.get('power', 0) for d in detections]
        avg_power = sum(powers) / len(powers) if powers else 0
        
        # Most common pattern (use first one as representative)
        pattern = detections[0].get('pattern', '')
        
        # Average frequency
        freqs = [d.get('frequency', 0) for d in detections]
        avg_freq = sum(freqs) / len(freqs) if freqs else 0
        
        # Average pulse count
        pulse_counts = [d.get('num_pulses', 0) for d in detections]
        avg_pulses = sum(pulse_counts) / len(pulse_counts) if pulse_counts else 0
        
        return {
            'timestamp': first_time,
            'pattern': pattern,
            'frequency': avg_freq,
            'power': avg_power,
            'repetition_count': len(detections),
            'time_span_ms': time_span_ms,
            'avg_pulse_count': avg_pulses,
            'individual_detections': detections,
            'is_grouped': True
        }
    
    def get_recent_groups(self, max_age_s: float = 5.0) -> List[Dict]:
        """Get recently grouped detections.
        
        Args:
            max_age_s: Maximum age in seconds
            
        Returns:
            List of recent grouped detections
        """
        current_time = time.time()
        recent = []
        
        for group in self.groups:
            if current_time - group['timestamp'] <= max_age_s:
                recent.append(group)
        
        return recent
    
    def clear_old_groups(self, max_age_s: float = 60.0):
        """Remove old grouped detections from memory.
        
        Args:
            max_age_s: Maximum age to keep in seconds
        """
        current_time = time.time()
        self.groups = [
            g for g in self.groups 
            if current_time - g['timestamp'] <= max_age_s
        ]
