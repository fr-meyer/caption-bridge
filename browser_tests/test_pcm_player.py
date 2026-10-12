"""Silent deterministic clocks and fake sources exercise the production PCM player."""
from pathlib import Path

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.browser
SOURCE = Path(__file__).parents[1] / "app/static/pcm-player.js"
SETUP = """() => {
 window.events = []; window.nodes = []; window.ctx = {currentTime: 0, destination: {},
 resume: () => window.defer ? new Promise(r => window.resolveResume = r) : Promise.resolve(),
 createBuffer: (_, n) => {const data = new Float32Array(n); return {getChannelData:()=>data, length:n};},
 createBufferSource: () => {const node = {connect(){}, start(at){this.at=at;},stop(){this.stopped=true;}};
 window.nodes.push(node); return node;}};
 window.streaming = true;
 window.player = new CaptionPcmPlayer({context:()=>ctx, streaming:()=>window.streaming,canPlay:()=>true,
 onFirstChunk:m=>events.push(['chunk',m.clip_id]),onStart:m=>events.push(['start',m.clip_id]),
 onComplete:(m,s)=>events.push(['complete',m.clip_id,s]),onError:(m,r)=>events.push(['error',m.clip_id,r]),onLocked:()=>{}});
 window.msg = (id,index,last=false,data=null) => ({seq:1,tts_epoch:0,clip_id:id,chunk_index:index,is_last:last,data});
 window.pcm = n => {const bytes = new Uint8Array(n*4); return btoa(String.fromCharCode(...bytes));};
}"""


def _setup(page):
    page.goto("about:blank")
    page.add_script_tag(path=str(SOURCE))
    page.evaluate(SETUP)


def test_streaming_starts_before_eos_keeps_order_and_measures_late_chunks(page: Page):
    _setup(page)
    page.evaluate("player.receive(msg(1,0,false,pcm(3600)))")
    page.wait_for_function("nodes.length === 1")
    assert page.evaluate("nodes[0].at") == pytest.approx(0.02)
    page.evaluate("player.receive(msg(2,0,true,pcm(3600))); player.receive(msg(1,1,false,pcm(3600)))")
    assert page.evaluate("nodes.length") == 2
    assert page.evaluate("nodes[1].at") == pytest.approx(0.17)
    page.evaluate("ctx.currentTime=0.4; player.receive(msg(1,2,false,pcm(3600))); player.receive(msg(1,3,true)); nodes.slice(0,3).forEach(n=>n.onended())")
    page.wait_for_function("nodes.length === 4")
    result = page.evaluate("events.find(e=>e[0]==='complete')[2]")
    assert result["underruns"] == 1 and result["gap_ms"] == 100
    assert page.evaluate("events.filter(e=>e[0]==='start').map(e=>e[1])") == [1, 2]


def test_buffered_fallback_and_odd_byte_boundary_decode_exactly(page: Page):
    _setup(page)
    page.evaluate("streaming=false; player.receive(msg(1,0,false,btoa(String.fromCharCode(0,0,0))))")
    assert page.evaluate("nodes.length") == 0
    page.evaluate("player.receive(msg(1,1,true,btoa(String.fromCharCode(0))))")
    page.wait_for_function("nodes.length === 1")
    assert page.evaluate("nodes[0].buffer.length") == 1
    page.evaluate("nodes[0].onended()")
    assert page.evaluate("events.find(e=>e[0]==='complete')[2].mode") == "buffered"
    assert page.evaluate("player.bytes") == 0
    page.evaluate("player.receive(msg(1,0,true,pcm(1)))")
    assert page.evaluate("nodes.length") == 1  # Completed clip retransmission is ignored.


def test_cancel_pending_resume_active_sources_and_failed_replay_are_isolated(page: Page):
    _setup(page)
    page.evaluate("defer=true; player.receive(msg(1,0,true,pcm(3600)))")
    page.wait_for_function("typeof resolveResume === 'function'")
    page.evaluate("player.cancelAll(); defer=false; resolveResume()")
    assert page.evaluate("nodes.length") == 0
    page.evaluate("player.receive(msg(2,0,true,pcm(3600)))")
    page.wait_for_function("nodes.length === 1")
    page.evaluate("player.receive(msg(3,0,true,pcm(3600))); player.begin(msg(4,0)); player.cancel(msg(4,0)); nodes[0].onended()")
    page.wait_for_function("nodes.length === 2")
    assert page.evaluate("events.filter(e=>e[0]==='start').map(e=>e[1])") == [2, 3]
    page.evaluate("player.cancelAll()")
    assert page.evaluate("nodes[1].stopped && player.bytes===0 && player.clips.size===0")


def test_limits_duplicates_missing_chunks_timeout_and_invalid_pcm(page: Page):
    _setup(page)
    page.evaluate("player.maxClipBytes=16; player.receive(msg(1,0,false,pcm(5)))")
    assert page.evaluate("events.pop()[2]") == "buffer_limit"
    page.evaluate("player.maxClipBytes=1000; player.receive(msg(2,0,false,pcm(1))); player.receive(msg(2,0,false,pcm(1)))")
    assert page.evaluate("player.bytes") == 4
    page.evaluate("player.receive(msg(2,2,true))")
    assert page.evaluate("events.pop()[2]") == "missing_chunk"
    page.evaluate("player.receive(msg(3,0,true,btoa('x')))")
    assert page.evaluate("events.pop()[2]") == "invalid_pcm"
    page.evaluate("player.timeoutMs=10; player.begin(msg(4,0))")
    page.wait_for_function("events.some(e=>e[2]==='stream_timeout')")
    assert page.evaluate("player.bytes===0 && player.clips.size===0")


def test_controlled_ab_startup_metrics_distinguish_buffering_from_playback(page: Page):
    _setup(page)
    results = page.evaluate("""async () => {
        const results = {};
        for (const mode of ['buffered', 'streaming']) {
            let clock = 0;
            const p = new CaptionPcmPlayer({context:()=>ctx, clock:()=>clock,
                streaming:()=>mode==='streaming', canPlay:()=>true, onFirstChunk:()=>{},
                onStart:()=>{}, onError:()=>{throw new Error('Unexpected PCM failure');},
                onLocked:()=>{}, onComplete:(_m,s)=>results[mode]=s});
            for (let index=0; index<4; index++) {
                clock = index*100;
                p.receive(msg(10,index,false,pcm(1200)));
                await Promise.resolve();
            }
            clock = 400;
            p.receive(msg(10,4,true));
            await Promise.resolve();
            Array.from(p.active.nodes).forEach(node=>node.onended());
        }
        return results;
    }""")
    assert results['streaming']['first_chunk_to_playback_ms'] == 200
    assert results['streaming']['initial_buffer_ms'] == 200
    assert results['buffered']['first_chunk_to_playback_ms'] == 400
    assert results['buffered']['initial_buffer_ms'] == 400
    assert results['streaming']['underruns'] == results['buffered']['underruns'] == 0
