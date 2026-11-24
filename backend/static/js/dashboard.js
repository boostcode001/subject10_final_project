(function () {
    "use strict";

    const dataElement = document.getElementById("dashboard-data");
    if (!dataElement) {
        return;
    }
    const data = JSON.parse(dataElement.textContent);

    const ACTION_COLOR = "#3b4fd8";
    const UNKNOWN_COLOR = "#d97706";
    const STATUS_COLORS = {
        PENDING: "#9ca3af",
        PROCESSING: "#3b4fd8",
        COMPLETED: "#16a34a",
        FAILED: "#dc2626",
    };

    function percent(value) {
        return value === null ? "-" : `${Math.round(value * 100)}%`;
    }

    function showFallback(canvasId, message) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) {
            return;
        }
        const card = canvas.closest(".card");
        const fallback = card.querySelector(".chart-fallback");
        canvas.parentElement.hidden = true;
        fallback.textContent = message;
        fallback.hidden = false;
    }

    function drawActionChart() {
        const actions = data.actions;
        if (!actions.some((item) => item.count > 0)) {
            showFallback("action-chart", "아직 판정된 결과가 없습니다.");
            return;
        }
        new Chart(document.getElementById("action-chart"), {
            type: "bar",
            data: {
                labels: actions.map((item) => item.label),
                datasets: [
                    {
                        label: "예측 건수",
                        data: actions.map((item) => item.count),
                        backgroundColor: actions.map((item) =>
                            item.value === "UNKNOWN" ? UNKNOWN_COLOR : ACTION_COLOR
                        ),
                        borderRadius: 6,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (context) => `예측 ${context.parsed.y}건`,
                            afterLabel: (context) =>
                                `평균 신뢰도 ${percent(actions[context.dataIndex].avg_confidence)}`,
                        },
                    },
                },
                scales: {
                    y: { beginAtZero: true, ticks: { precision: 0 } },
                },
            },
        });
    }

    function drawStatusChart() {
        const statuses = data.statuses;
        if (!statuses.some((item) => item.count > 0)) {
            showFallback("status-chart", "아직 분석 작업이 없습니다.");
            return;
        }
        new Chart(document.getElementById("status-chart"), {
            type: "doughnut",
            data: {
                labels: statuses.map((item) => item.label),
                datasets: [
                    {
                        data: statuses.map((item) => item.count),
                        backgroundColor: statuses.map((item) => STATUS_COLORS[item.value] || "#9ca3af"),
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: "bottom" },
                    tooltip: {
                        callbacks: {
                            label: (context) => `${context.label}: ${context.parsed}건`,
                        },
                    },
                },
            },
        });
    }

    if (typeof Chart === "undefined") {
        const message = "차트를 불러오지 못했습니다(인터넷 연결 확인). 아래 표의 숫자를 확인하세요.";
        showFallback("action-chart", message);
        showFallback("status-chart", message);
        return;
    }

    drawActionChart();
    drawStatusChart();
})();