"""Nonblocking LLM command generation and deterministic receiver checks."""
import json
import math
import queue
import threading
import time
import urllib.request


def validate_target(payload):
    if not isinstance(payload, dict) or set(payload) != {'target'}:
        raise ValueError('Expected only a target field')
    target = payload['target']
    if not isinstance(target, list) or len(target) != 3 or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
            for v in target):
        raise ValueError('target must contain three finite XYZ numbers')
    return tuple(float(v) for v in target)


class CommandReceiver:
    def __init__(self):
        self.last_sequence = 0
        self.latched = False

    def receive(self, command, now, delivered):
        # Latching takes priority: no late command may restart mission flight.
        if self.latched:
            return 'suppressed_after_timeout'
        if not delivered:
            return 'dropped'
        if command['sequence'] <= self.last_sequence:
            return 'duplicate_or_out_of_order'
        if now >= command['expires_at']:
            return 'expired'
        self.last_sequence = command['sequence']
        return 'accepted'


class LLMCommandWorker:
    """One daemon worker; network requests never run on the watchdog thread."""
    def __init__(self, provider, model, timeout, ttl, prompt):
        self.provider, self.model, self.timeout, self.ttl, self.prompt = provider, model, timeout, ttl, prompt
        self.requests, self.results = queue.Queue(maxsize=1), queue.Queue(maxsize=1)
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._work, daemon=True)
        self.thread.start()

    def submit(self, sequence, state):
        self.requests.put_nowait((sequence, state, time.monotonic()))

    def poll(self):
        try:
            return self.results.get_nowait()
        except queue.Empty:
            return None

    def close(self):
        self.stopping.set()  # Bounded provider request may finish; no blocking join at cleanup.

    def _generate(self, state):
        system = ('Return JSON only: {"target":[x,y,z]}. Propose exactly one absolute AirSim NED '
                  'waypoint for the mission. Z is positive down. Do not issue takeoff, landing, '
                  'arming, or other actions. Keep the requested cruise Z. Mission context: ' + json.dumps(state))
        if self.provider == 'ollama':
            body = json.dumps(dict(model=self.model, stream=False, format='json',
                                   messages=[dict(role='system', content=system),
                                             dict(role='user', content=self.prompt)],
                                   options=dict(temperature=0))).encode()
            request = urllib.request.Request('http://localhost:11434/api/chat', data=body,
                                             headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read())['message']['content']
        from openai import OpenAI
        with OpenAI(max_retries=0, timeout=self.timeout) as client:
            response = client.chat.completions.create(model=self.model,
                messages=[dict(role='system', content=system), dict(role='user', content=self.prompt)],
                response_format={'type': 'json_object'})
            return response.choices[0].message.content

    def _work(self):
        while not self.stopping.is_set():
            try:
                sequence, state, created = self.requests.get(timeout=.1)
            except queue.Empty:
                continue
            try:
                target = validate_target(json.loads(self._generate(state)))
                result = dict(sequence=sequence, target=target, created_at=created,
                              expires_at=created+self.ttl, inference_latency_s=time.monotonic()-created)
            except Exception as exc:
                # Do not log provider error bodies that could contain sensitive request details.
                result = dict(sequence=sequence, error_type=type(exc).__name__,
                              inference_latency_s=time.monotonic()-created)
            if not self.stopping.is_set():
                self.results.put(result)
