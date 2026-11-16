import asyncio
import time

from src.services.loop_watchdog import LoopWatchdog


def blocking_step_in_the_loop():
    time.sleep(1.0)


def test_a_stalled_event_loop_is_reported_with_where_it_was_stuck():
    reports = []

    async def scenario():
        dog = LoopWatchdog(asyncio.get_running_loop(), threshold=0.4, interval=0.05,
                           report=lambda delay, stacks: reports.append((delay, stacks)))
        dog.start()
        await asyncio.sleep(0.3)  # a healthy loop reports nothing
        assert reports == []
        blocking_step_in_the_loop()  # holds the loop for a second
        await asyncio.sleep(0.3)
        dog.stop()

    asyncio.run(scenario())
    assert len(reports) == 1  # one report per stall, not one per check
    delay, stacks = reports[0]
    assert delay >= 0.4
    assert 'blocking_step_in_the_loop' in stacks


def test_a_healthy_loop_is_never_reported():
    reports = []

    async def scenario():
        dog = LoopWatchdog(asyncio.get_running_loop(), threshold=0.4, interval=0.05,
                           report=lambda delay, stacks: reports.append(delay))
        dog.start()
        for _ in range(10):
            await asyncio.sleep(0.05)
        dog.stop()

    asyncio.run(scenario())
    assert reports == []
