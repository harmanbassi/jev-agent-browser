"""Opt-in paid paired evaluation. Never mounts or adopts personal browser identities."""
import json
import os

import pytest

from jev_browser import environment
from jev_browser.client import Browser

pytestmark = pytest.mark.skipif(os.environ.get('JEV_LIVE_VISION') != '1',
                                reason='paid visual evaluation is explicit opt-in')


@pytest.mark.parametrize('mode', ['off', 'auto', 'always'])
@pytest.mark.parametrize('swapped', [False, True])
def test_paired_visual_selection(mode, swapped, record_property):
    """Measure completion separately from safety; safe pauses are part of the contract.

    Ambiguous equal labels deliberately cannot establish color from DOM alone.
    The task caller supplies require_visual for both image modes, as documented.
    """
    reader = dict(os.environ)
    reader.update(JEV_VISION_MODE='auto', JEV_VISION_MAX_CALLS='8')
    # Permission must come from the operator; this evaluation never grants it.
    with environment.use(reader.get), Browser() as browser:
        opened = browser.open('https://example.com/')
        assert opened['status'] == 'ready', opened
        sid = opened['session_id']
        session = browser._sessions[sid]
        colors = ['red', 'blue'] if swapped else ['blue', 'red']
        buttons = ''.join(
            '<button style="background:' + color + ';width:180px;height:150px;margin:30px;color:white" '
            'onclick="document.getElementById(\'result\').textContent=\'Selected ' + color + '\'">Choose</button>'
            for color in colors)
        html = '<title>Visual evaluation</title>' + buttons + '<p id="result"></p>'
        session.cf.evaluate('(()=>{document.body.innerHTML=' + json.dumps(html) + ';return true})()')
        out = browser.run(sid, 'Click the red button. Finish only when Selected red is visibly shown.',
                          vision=mode, require_visual=mode != 'off', max_steps=5, timeout=180)
        correct = 'Selected red' in session.cf.evaluate('document.body.innerText')
        record_property('evaluation', json.dumps({'mode': mode, 'swapped': swapped, 'status': out['status'],
            'correct': correct, 'reason': out.get('reason'), 'vision': out.get('vision'),
            'models': out.get('models'), 'confidence': out.get('confidence'),
            'target_confidence': out.get('target_confidence'), 'elapsed_ms': out['elapsed_ms']}))
        if mode == 'off':
            assert 'vision' not in out
        else:
            assert out['status'] in {'done', 'paused'}, out
            assert out['vision']['models'], out
            if out['status'] == 'done':
                assert correct and out['vision']['verified'], out
            else:
                assert out['reason'] in {'low_confidence', 'need_guidance', 'blocked', 'no_progress',
                                        'vision_completion_unverified', 'vision_budget', 'vision_capture_budget'}, out
                assert not out['vision']['verified'], out
                # A conservative pause must never conceal execution of the wrong target.
                assert 'Selected blue' not in session.cf.evaluate('document.body.innerText'), out
        assert browser.close(sid)['status'] == 'closed'
