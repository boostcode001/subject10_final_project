(function () {
    "use strict";

    const configElement = document.getElementById("page-config");
    const config = configElement ? JSON.parse(configElement.textContent) : {};
    const POLL_MS = 2000;
    const RECORDING_POLL_MS = 1000;
    const STEP_ORDER = ["waiting", "recording", "analyzing", "completed"];

    const PHASE_TEXT = {
        waiting: "대기 중입니다. 곧 시작됩니다.",
        recording: "녹화 중입니다. 카메라 앞에서 동작을 해 주세요.",
        analyzing: "AI가 영상을 분석하고 있습니다.",
        completed: "분석이 완료되었습니다.",
        failed: "분석에 실패했습니다.",
    };
    const STATUS_TEXT = { PENDING: "대기", PROCESSING: "처리 중", COMPLETED: "완료", FAILED: "실패" };
    const INPUT_TEXT = { UPLOAD: "업로드", WEBCAM: "웹캠" };

    let pollTimer = null;
    let currentJobId = null;
    let stopRequested = false;

    function getCookie(name) {
        const match = document.cookie.split("; ").find((row) => row.startsWith(name + "="));
        return match ? decodeURIComponent(match.split("=")[1]) : "";
    }

    function errorText(data, status) {
        if (!data) {
            return `요청에 실패했습니다 (HTTP ${status}).`;
        }
        if (data.detail) {
            return data.detail;
        }
        return Object.values(data).flat().join(" ");
    }

    async function api(url, options = {}) {
        const response = await fetch(url, {
            credentials: "same-origin",
            ...options,
            headers: {
                Accept: "application/json",
                "X-CSRFToken": getCookie("csrftoken"),
                ...(options.headers || {}),
            },
        });
        let data = null;
        try {
            data = await response.json();
        } catch (error) {
            data = null;
        }
        if (!response.ok) {
            throw new Error(errorText(data, response.status));
        }
        return data;
    }

    function showError(message) {
        const box = document.getElementById("form-error");
        if (!box) {
            return;
        }
        box.textContent = message || "";
        box.hidden = !message;
    }

    function setBusy(busy) {
        document.querySelectorAll("#upload-form button, #webcam-form button").forEach((button) => {
            button.disabled = busy;
        });
    }

    async function renderSidebar() {
        const list = document.getElementById("sidebar-list");
        if (!list) {
            return;
        }
        const activeId = Number(list.dataset.activeId || 0);
        try {
            const data = await api("/api/analyses/");
            const jobs = data.results || [];
            list.innerHTML = "";
            if (!jobs.length) {
                list.innerHTML = '<li class="sidebar-empty">아직 분석 기록이 없습니다.</li>';
                return;
            }
            jobs.forEach((job) => {
                const item = document.createElement("li");
                item.className = "sidebar-item" + (job.id === activeId ? " is-active" : "");
                item.innerHTML =
                    `<a href="/analyses/${job.id}/">` +
                    '<span class="sidebar-title"></span>' +
                    '<span class="sidebar-meta">' +
                    `<span class="badge badge-${job.status.toLowerCase()}">${STATUS_TEXT[job.status] || job.status}</span>` +
                    ` ${INPUT_TEXT[job.input_type] || ""}</span>` +
                    '<span class="sidebar-action"></span></a>';
                item.querySelector(".sidebar-title").textContent = job.title || `작업 #${job.id}`;
                item.querySelector(".sidebar-action").textContent = job.top_action
                    ? `${job.top_action.display} · ${Math.round(job.top_action.confidence * 100)}%`
                    : job.result_message || "";
                list.appendChild(item);
            });
        } catch (error) {
            list.innerHTML = '<li class="sidebar-empty">기록을 불러오지 못했습니다.</li>';
        }
    }

    function updateRecordingBar(status) {
        const bar = document.getElementById("recording-bar");
        const button = document.getElementById("stop-button");
        if (!bar || !button) {
            return;
        }
        const recording = status.phase === "recording";
        bar.hidden = !recording;
        if (!recording) {
            return;
        }
        const elapsed = status.started_at ? (Date.now() - Date.parse(status.started_at)) / 1000 : 0;
        const minSeconds = config.cameraMinSeconds || 5;
        const maxSeconds = config.cameraMaxSeconds || 10;
        document.getElementById("recording-timer").textContent =
            `녹화 ${Math.floor(elapsed)}초 / 최대 ${maxSeconds}초`;

        const canStop = elapsed >= minSeconds && !stopRequested;
        button.disabled = !canStop;
        if (stopRequested) {
            button.textContent = "종료 요청됨";
        } else if (canStop) {
            button.textContent = "녹화 종료";
        } else {
            button.textContent = `${Math.ceil(minSeconds - elapsed)}초 후 종료 가능`;
        }
    }

    function updateStatusCard(status) {
        const card = document.getElementById("status-card");
        if (!card) {
            return;
        }
        card.hidden = false;
        card.classList.toggle("is-webcam", status.input_type === "WEBCAM");
        card.classList.toggle("is-failed", status.phase === "failed");

        const currentIndex = STEP_ORDER.indexOf(status.phase);
        card.querySelectorAll(".stepper li").forEach((step) => {
            const index = STEP_ORDER.indexOf(step.dataset.step);
            const done = status.phase === "completed" || (currentIndex >= 0 && index < currentIndex);
            step.classList.toggle("is-done", done);
            step.classList.toggle("is-current", index === currentIndex && status.phase !== "completed");
        });

        const message = status.phase === "failed"
            ? `${PHASE_TEXT.failed} ${status.error_message || ""}`
            : PHASE_TEXT[status.phase] || "";
        document.getElementById("status-message").textContent = message;
        updateRecordingBar(status);
    }

    async function poll(jobId, onFinished) {
        try {
            const status = await api(`/api/analyses/${jobId}/status/`);
            updateStatusCard(status);
            if (status.is_finished) {
                onFinished(status);
                return;
            }
            const delay = status.phase === "recording" ? RECORDING_POLL_MS : POLL_MS;
            pollTimer = setTimeout(() => poll(jobId, onFinished), delay);
        } catch (error) {
            showError(error.message);
            pollTimer = setTimeout(() => poll(jobId, onFinished), POLL_MS * 2);
        }
    }

    function startTracking(jobId) {
        currentJobId = jobId;
        stopRequested = false;
        clearTimeout(pollTimer);
        poll(jobId, () => {
            window.location.href = `/analyses/${jobId}/`;
        });
    }

    async function createJob(formData) {
        showError("");
        setBusy(true);
        for (const [key, value] of [...formData.entries()]) {
            if (value === "") {
                formData.delete(key);
            }
        }
        try {
            const job = await api("/api/analyses/", { method: "POST", body: formData });
            startTracking(job.id);
            renderSidebar();
        } catch (error) {
            showError(error.message);
            setBusy(false);
        }
    }

    async function stopRecording() {
        if (!currentJobId) {
            return;
        }
        const button = document.getElementById("stop-button");
        button.disabled = true;
        try {
            await api(`/api/analyses/${currentJobId}/stop/`, { method: "POST" });
            stopRequested = true;
            button.textContent = "종료 요청됨";
        } catch (error) {
            showError(error.message);
        }
    }

    function setupTabs() {
        const tabs = document.querySelectorAll(".tab");
        tabs.forEach((tab) => {
            tab.addEventListener("click", () => {
                const name = tab.dataset.tab;
                tabs.forEach((other) => other.classList.toggle("is-active", other === tab));
                document.querySelectorAll(".tab-panel").forEach((panel) => {
                    panel.classList.toggle("is-active", panel.dataset.panel === name);
                });
                showError("");
            });
        });
    }

    function setupForms() {
        const uploadForm = document.getElementById("upload-form");
        if (uploadForm) {
            uploadForm.addEventListener("submit", (event) => {
                event.preventDefault();
                const data = new FormData(uploadForm);
                data.append("input_type", "UPLOAD");
                createJob(data);
            });
        }

        const webcamForm = document.getElementById("webcam-form");
        if (webcamForm) {
            webcamForm.addEventListener("submit", (event) => {
                event.preventDefault();
                const data = new FormData(webcamForm);
                data.append("input_type", "WEBCAM");
                createJob(data);
            });
        }

        const stopButton = document.getElementById("stop-button");
        if (stopButton) {
            stopButton.addEventListener("click", stopRecording);
        }
    }

    function setupResultPage() {
        if (!config.jobId || config.isFinished) {
            return;
        }
        currentJobId = config.jobId;
        poll(config.jobId, () => window.location.reload());
    }

    setupTabs();
    setupForms();
    setupResultPage();
    renderSidebar();
})();