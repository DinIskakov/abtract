import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import HttpUrl, SecretStr

from app import experiments, gemini, task_generation
from app.artifacts import save_artifact
from app.config import settings
from app.evaluations import Criterion, TaskRubric, content_hash, evaluate
from app.experiments import Experiment, ExperimentRequest
from app.observability import HTTPObservation, Observations
from app.proposals import ProposalReport, ProposedPatch, SourceDocument
from app.routers.experiments import create_experiment, experiment_options
from app.runs import AgentReport, HarnessConfig, RunResult
from app.task_generation import PageError, fetch_page, generate_tasks, public_address
from app.variants import VariantPatch, variant_hash

PAGE = SourceDocument(
    url=HttpUrl("https://example.com/"),
    body="<html><h1>Example is a platform for building reliable widgets.</h1></html>",
)


def rubric() -> TaskRubric:
    return TaskRubric(
        task_id="task-1",
        task_index=0,
        task="What is Example for?",
        criteria=[
            Criterion(
                id="answer",
                kind="required_text",
                description="Correct purpose",
                values=["widgets"],
            )
        ],
    )


def result(request, harness):
    return RunResult(
        task=request.tasks[0],
        task_index=0,
        repetition=1,
        harness=harness,
        harness_version="test",
        status="completed",
        variant_id=request.variant_id,
        duration_seconds=100,
        execution_duration_seconds=20 if request.variant_id == "baseline" else 5,
        report=AgentReport(
            answer="widgets", actions=[], sources=[str(PAGE.url)], limitations=[]
        ),
        observations=Observations(
            http=[
                HTTPObservation(
                    url=str(PAGE.url),
                    method="GET",
                    started_at=1,
                    duration_ms=1,
                    status_code=200,
                    original_sha256=content_hash(PAGE.body),
                    original_body=PAGE.body,
                )
            ]
        ),
    )


@pytest.mark.parametrize("with_patch", [False, True])
def test_pipeline_order_identical_questions_and_full_parallelism(
    monkeypatch, tmp_path, with_patch
):
    monkeypatch.setattr(settings, "artifact_dir", tmp_path)
    monkeypatch.setattr(experiments, "fetch_page", AsyncMock(return_value=PAGE))
    generator = AsyncMock(return_value=[rubric()])
    monkeypatch.setattr(experiments, "generate_tasks", generator)
    stages = []
    requests = []
    graded_rubrics = []
    original_persist = experiments.persist

    async def persist(experiment, phase):
        stages.append(phase)
        await original_persist(experiment, phase)

    async def run(request):
        requests.append(request)
        return [result(request, harness) for harness in request.harnesses]

    async def grade(request):
        assert request.semantic_judge is True
        graded_rubrics.append(request.rubrics)
        return await evaluate(request.model_copy(update={"semantic_judge": False}))

    async def propose(request):
        # Correct answers still expose a real, independently measured latency failure.
        assert request.evaluation.failed == 2
        for run in request.evaluation.runs:
            checks = {check.check_id: check for check in run.checks}
            assert checks["answer"].outcome == "pass"
            assert checks["agent_latency"].outcome == "fail"
        patch = VariantPatch(
            patch_id="patch-1",
            url=PAGE.url,
            expected_sha256=content_hash(PAGE.body),
            old_text="reliable widgets",
            new_text="reliable, reusable widgets",
        )
        patches = (
            [
                ProposedPatch(
                    patch=patch,
                    rationale="Clarify wording",
                    failed_check_refs=[
                        f"{request.evaluation.runs[0].run_id}/agent_latency"
                    ],
                )
            ]
            if with_patch
            else []
        )
        return ProposalReport(
            evaluation_id=request.evaluation.evaluation_id,
            variant_id="variant-test",
            variant_sha256=variant_hash([p.patch for p in patches]),
            summary="Clarify wording" if patches else "No failed checks.",
            patches=patches,
        )

    monkeypatch.setattr(experiments, "persist", persist)
    monkeypatch.setattr(experiments, "create_runs", run)
    monkeypatch.setattr(experiments, "create_evaluation", grade)
    monkeypatch.setattr(experiments, "create_proposal", propose)

    async def check():
        started = await experiments.start_experiment(
            ExperimentRequest(
                url=PAGE.url,
                harnesses=[HarnessConfig(name="codex"), HarnessConfig(name="gemini")],
                task_count=1,
                difficulty="medium",
                latency_budget_seconds=10,
            )
        )
        assert started.phase == "planning"
        await experiments.jobs[started.experiment_id]
        final = await experiments.read_experiment(started.experiment_id)
        assert final.phase == "completed"
        assert final.difficulty == "medium"
        assert final.latency_budget_seconds == 10
        generator.assert_awaited_once_with(PAGE, 1, "medium")
        assert final.tasks[0].criteria[-1].limit == 10
        assert final.concurrency == requests[0].max_concurrency == 2
        assert requests[0].capture_http is True
        assert requests[0].retrieval_mode == "direct_http"
        assert stages == [
            "planning",
            "baseline",
            "baseline_evaluation",
            "proposing",
            *(["variant", "variant_evaluation"] if with_patch else []),
            "completed",
        ]
        if with_patch:
            assert requests[0].tasks == requests[1].tasks
            assert requests[0].harnesses == requests[1].harnesses
            assert requests[1].max_concurrency == 2
            assert final.variant_evaluation is not None
            assert final.variant_evaluation.passed == 2
            assert graded_rubrics[0] == graded_rubrics[1]
        else:
            assert final.variant_runs == []
        public = experiments.public_experiment(final)
        assert public.baseline_runs[0].observations.http[0].original_body is None
        assert final.baseline_runs[0].observations.http[0].original_body == PAGE.body

    asyncio.run(check())


def test_failure_and_server_restart_are_persisted(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "artifact_dir", tmp_path)
    monkeypatch.setattr(
        experiments, "fetch_page", AsyncMock(side_effect=PageError("Page too large"))
    )

    async def check():
        started = await experiments.start_experiment(
            ExperimentRequest(url=PAGE.url, harnesses=[HarnessConfig(name="gemini")])
        )
        await experiments.jobs[started.experiment_id]
        final = await experiments.read_experiment(started.experiment_id)
        assert final.phase == "failed" and final.error == "Page too large"
        stale = Experiment(url=PAGE.url, harnesses=[], concurrency=1)
        save_artifact("experiments", stale.experiment_id, stale)
        recovered = await experiments.read_experiment(stale.experiment_id)
        assert recovered.phase == "failed" and "restarted" in recovered.error

    asyncio.run(check())


def test_shutdown_cancels_jobs_and_records_interruption(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "artifact_dir", tmp_path)

    async def check():
        entered = asyncio.Event()

        async def fetch(url):
            entered.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(experiments, "fetch_page", fetch)
        started = await experiments.start_experiment(
            ExperimentRequest(url=PAGE.url, harnesses=[HarnessConfig(name="gemini")])
        )
        await entered.wait()
        await experiments.shutdown_experiments()
        assert not experiments.jobs
        final = await experiments.read_experiment(started.experiment_id)
        assert final.phase == "failed" and "shutdown" in final.error

    asyncio.run(check())


def test_poll_does_not_overwrite_completion_when_job_finishes_during_read(monkeypatch):
    stale = Experiment(url=PAGE.url, harnesses=[], concurrency=1, phase="baseline")
    persisted = AsyncMock()
    monkeypatch.setattr(experiments, "persist", persisted)

    async def threaded_read(*args):
        # Simulate loading a stale snapshot immediately before the job completes.
        experiments.jobs.pop(stale.experiment_id)
        return stale.model_dump(mode="json")

    monkeypatch.setattr(experiments.asyncio, "to_thread", threaded_read)

    async def check():
        experiments.jobs[stale.experiment_id] = asyncio.current_task()
        response = await experiments.read_experiment(stale.experiment_id)
        assert response.phase == "baseline"
        persisted.assert_not_called()

    asyncio.run(check())


def test_source_mismatch_stops_before_patches(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "artifact_dir", tmp_path)
    monkeypatch.setattr(experiments, "fetch_page", AsyncMock(return_value=PAGE))
    monkeypatch.setattr(
        experiments, "generate_tasks", AsyncMock(return_value=[rubric()])
    )
    proposer = AsyncMock()
    monkeypatch.setattr(experiments, "create_proposal", proposer)

    async def run(request):
        record = result(request, request.harnesses[0])
        record.observations.http[0].original_sha256 = "changed-page"
        return [record]

    async def grade(request):
        return await evaluate(request.model_copy(update={"semantic_judge": False}))

    monkeypatch.setattr(experiments, "create_runs", run)
    monkeypatch.setattr(experiments, "create_evaluation", grade)

    async def check():
        started = await experiments.start_experiment(
            ExperimentRequest(
                url=PAGE.url, harnesses=[HarnessConfig(name="gemini")], task_count=1
            )
        )
        await experiments.jobs[started.experiment_id]
        final = await experiments.read_experiment(started.experiment_id)
        assert final.phase == "completed" and "not observed consistently" in final.note
        assert final.baseline_evaluation is not None
        proposer.assert_not_called()

    asyncio.run(check())


def test_supervisor_required_independent_of_selected_harness(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", None)
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("test-key"))
    options = asyncio.run(experiment_options())
    assert not options.supervisor.available
    assert next(item for item in options.harnesses if item.name == "codex").available
    with pytest.raises(Exception) as caught:
        asyncio.run(
            create_experiment(
                ExperimentRequest(url=PAGE.url, harnesses=[HarnessConfig(name="codex")])
            )
        )
    assert caught.value.status_code == 503


@pytest.mark.parametrize(
    "quote",
    [
        "Example is a platform for building reliable widgets.",
        "Invented claim about widgets.",
    ],
)
def test_generated_questions_require_exact_source_quotes(monkeypatch, quote):
    mock = AsyncMock(
        return_value=gemini.Generation(
            data={
                "tasks": [
                    {
                        "question": "What does Example help build?",
                        "reference_answer": "Reliable widgets.",
                        "source_quote": quote,
                    }
                ]
            },
            requested_model="test",
        )
    )
    monkeypatch.setattr(gemini, "generate", mock)
    if quote.startswith("Invented"):
        with pytest.raises(gemini.GeminiError, match="quote"):
            asyncio.run(generate_tasks(PAGE, 1))
    else:
        tasks = asyncio.run(generate_tasks(PAGE, 1))
        assert tasks[0].task == "What does Example help build?"
        assert quote in tasks[0].criteria[0].reference_answer
        assert "<html>" not in mock.call_args.args[1]["visible_text"]


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://169.254.169.254/",
        "http://[::1]/",
        "http://user:pass@example.com/",
        "https://example.com:1234/",
    ],
)
def test_private_or_credentialed_urls_rejected(url):
    with pytest.raises(PageError):
        asyncio.run(public_address(httpx.URL(url)))


def test_fetch_pins_address_and_blocks_private_redirect(monkeypatch):
    original_client = httpx.AsyncClient
    requests = []

    async def addresses(url):
        if url.host == "127.0.0.1":
            raise PageError("Only publicly routable page addresses are supported")
        return "93.184.216.34"

    def transport(request):
        requests.append(request)
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "example.com"
        assert request.extensions["sni_hostname"] == "example.com"
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    monkeypatch.setattr(task_generation, "public_address", addresses)
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(transport), **kwargs
        ),
    )
    with pytest.raises(PageError, match="publicly routable"):
        asyncio.run(fetch_page(PAGE.url))
    assert len(requests) == 1


def test_fetch_rejects_oversized_decoded_body(monkeypatch):
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        task_generation, "public_address", AsyncMock(return_value="93.184.216.34")
    )
    monkeypatch.setattr(task_generation, "MAX_PAGE_BYTES", 20)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, text=PAGE.body, headers={"content-type": "text/html"}
        )
    )
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )
    with pytest.raises(PageError, match="exceeds"):
        asyncio.run(fetch_page(PAGE.url))


def test_question_context_prefers_main_content_over_navigation():
    assert (
        task_generation.page_text(
            "<nav>Unrelated product menu</nav><main><p>Actual page purpose.</p>"
            "<script>ignore me</script></main>"
        )
        == "Actual page purpose."
    )


def test_fetch_canonicalizes_fragments_for_exact_http_matching(monkeypatch):
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        task_generation, "public_address", AsyncMock(return_value="93.184.216.34")
    )
    requests = []

    def respond(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(302, headers={"location": "/docs#usage"})
        return httpx.Response(
            200, text=PAGE.body, headers={"content-type": "text/html"}
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(respond), **kwargs
        ),
    )
    document = asyncio.run(fetch_page(HttpUrl("https://example.com/#intro")))
    assert str(document.url) == "https://example.com/docs"
    assert all(not request.url.fragment for request in requests)


@pytest.mark.parametrize(
    ("difficulty", "expected"),
    [
        ("easy", "VERY EASY factual"),
        ("medium", "short explanation"),
        ("hard", "synthesis, a tradeoff"),
    ],
)
def test_difficulty_controls_grounded_task_prompt(monkeypatch, difficulty, expected):
    generator = AsyncMock(
        return_value=gemini.Generation(
            data={
                "tasks": [
                    {
                        "question": "What does Example help build?",
                        "reference_answer": "Reliable widgets.",
                        "source_quote": (
                            "Example is a platform for building reliable widgets."
                        ),
                    }
                ]
            },
            requested_model="test",
        )
    )
    monkeypatch.setattr(gemini, "generate", generator)
    tasks = asyncio.run(generate_tasks(PAGE, 1, difficulty))
    instructions, payload, _ = generator.call_args.args
    assert expected in instructions
    assert "No external knowledge or browsing links" in instructions
    assert payload["difficulty"] == difficulty
    assert len(tasks) == 1


@pytest.mark.parametrize("budget", [0, -1, 181, float("inf"), float("nan")])
def test_latency_budget_bounds(budget):
    with pytest.raises(ValueError):
        ExperimentRequest(
            url=PAGE.url,
            harnesses=[HarnessConfig(name="codex")],
            latency_budget_seconds=budget,
        )
