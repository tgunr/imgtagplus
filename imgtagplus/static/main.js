/** Frontend controller for the single-page tagging UI and its long-running job state. */

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

async function readJson(res) {
    // Safari collapses .json() on a non-JSON body into its generic
    // "The string did not match the expected pattern." message, which hides the
    // real error (e.g. a plain-text 403/500 page). Read text first so callers
    // always get a readable detail string instead.
    const text = await res.text();
    if (!text) {
        return {};
    }
    try {
        return JSON.parse(text);
    } catch (_) {
        return { detail: text.trim() };
    }
}

document.addEventListener('DOMContentLoaded', () => {
    
    // UI Elements
    const modelSelect = document.getElementById('model-select');
    const modelWarning = document.getElementById('model-warning');
    const inputPath = document.getElementById('input-path');
    const thresholdInput = document.getElementById('threshold');
    const thresholdVal = document.getElementById('threshold-val');
    const maxTagsInput = document.getElementById('max-tags');
    const maxTagsVal = document.getElementById('max-tags-val');
    const recursiveCheck = document.getElementById('recursive');
    const overwriteCheck = document.getElementById('overwrite');
    const startBtn = document.getElementById('start-btn');
    const stopBtn = document.getElementById('stop-btn');
    const errorMsg = document.getElementById('error-msg');
    
    // Progress Elements
    const progressTitle = document.getElementById('progress-title');
    const progressFile = document.getElementById('progress-file');
    const progressPct = document.getElementById('progress-pct');
    const progressCounts = document.getElementById('progress-counts');
    const progressBar = document.getElementById('progress-bar');
    const runtimeClock = document.getElementById('runtime-clock');
    const logContainer = document.getElementById('log-container');
    const clearLogsBtn = document.getElementById('clear-logs');
    const copyLogsBtn = document.getElementById('copy-logs');
    const downloadLogBtn = document.getElementById('download-log');

    // Stats Elements
    const statsContainer = document.getElementById('stats-container');
    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');
    
    // Hardware Elements
    const hardwarePanel = document.getElementById('hardware-panel');
    const ramSpec = document.getElementById('ram-spec');
    const accelSpec = document.getElementById('accel-spec');
    const perfRating = document.getElementById('perf-rating');
    
    // Dialogs (native <dialog> elements)
    const helpDialog = document.getElementById('help-dialog');
    const perfDialog = document.getElementById('perf-dialog');
    const accelDialog = document.getElementById('accel-dialog');
    const filePickerDialog = document.getElementById('file-picker-dialog');
    const lightboxDialog = document.getElementById('lightbox-dialog');

    // Dialog openers
    const showTaggerViewBtn = document.getElementById('show-tagger-view');
    const showViewerViewBtn = document.getElementById('show-viewer-view');
    const helpBtn = document.getElementById('help-btn');
    const accelBox = document.getElementById('accel-box');
    const perfBox = document.getElementById('perf-box');
    const browseBtn = document.getElementById('browse-btn');
    const viewerBrowseBtn = document.getElementById('viewer-browse-btn');

    // File Picker Elements
    const cancelFilePickerBtn = document.getElementById('cancel-file-picker');
    const selectDirBtn = document.getElementById('select-dir-btn');
    const dirList = document.getElementById('dir-list');
    const currentDirPathSpan = document.getElementById('current-dir-path');

    // Output Dir Elements
    const outputToggle = document.getElementById('show-output-dir');
    const outputDirFields = document.getElementById('output-dir-fields');
    const outputDirInput = document.getElementById('output-dir');
    const outputBrowseBtn = document.getElementById('output-browse-btn');

    // View Containers
    const taggerView = document.getElementById('tagger-view');
    const viewerView = document.getElementById('viewer-view');

    // Viewer Elements
    const viewerPathInput = document.getElementById('viewer-path');
    const viewerLoadBtn = document.getElementById('viewer-load-btn');
    const viewerUseSourceBtn = document.getElementById('viewer-use-source-btn');
    const viewerRecursiveCheck = document.getElementById('viewer-recursive');
    const viewerSummary = document.getElementById('viewer-summary');
    const viewerErrorMsg = document.getElementById('viewer-error-msg');
    const viewerEmptyState = document.getElementById('viewer-empty-state');
    const viewerResults = document.getElementById('viewer-results');
    const viewerFooter = document.getElementById('viewer-footer');
    const viewerLoadMoreBtn = document.getElementById('viewer-load-more-btn');
    const viewerCountBadge = document.getElementById('viewer-count-badge');
    const viewerGridModeBtn = document.getElementById('viewer-grid-mode');
    const viewerListModeBtn = document.getElementById('viewer-list-mode');

    // Lightbox Elements
    const lightboxTitle = document.getElementById('lightbox-title');
    const lightboxPosition = document.getElementById('lightbox-position');
    const lightboxTagCount = document.getElementById('lightbox-tag-count');
    const lightboxPath = document.getElementById('lightbox-path');
    const lightboxImage = document.getElementById('lightbox-image');
    const lightboxCaption = document.getElementById('lightbox-caption');
    const lightboxTags = document.getElementById('lightbox-tags');
    const lightboxEmptyTags = document.getElementById('lightbox-empty-tags');
    const lightboxPrevBtn = document.getElementById('lightbox-prev-btn');
    const lightboxNextBtn = document.getElementById('lightbox-next-btn');
    const lightboxTagError = document.getElementById('lightbox-tag-error');
    const lightboxNewTagInput = document.getElementById('lightbox-new-tag-input');
    const lightboxAddTagBtn = document.getElementById('lightbox-add-tag-btn');

    // Manual Accelerator Elements
    const manualAccelToggle = document.getElementById('manual-accelerator');
    const manualAccelStatus = document.getElementById('manual-accel-status');
    const accelOptionsDiv = document.getElementById('accelerator-options');
    const accelRadios = document.getElementsByName('accel-choice');
    const accelCuda = document.getElementById('accel-cuda');
    const accelMps = document.getElementById('accel-mps');
    const accelCpu = document.getElementById('accel-cpu');
    const labelCuda = document.getElementById('label-accel-cuda');
    const labelMps = document.getElementById('label-accel-mps');
    const tipCuda = document.getElementById('tip-cuda');
    const tipMps = document.getElementById('tip-mps');
    const dialogStates = new WeakMap();
    const themeController = window.imgtagplusTheme;

    // Click handlers for tips (ensures visibility on mobile/click)
    [tipCuda, tipMps].forEach(tip => {
        tip.addEventListener('click', (e) => {
            const msg = tip.getAttribute('data-tooltip');
            if (msg) alert(msg);
            e.preventDefault();
            e.stopPropagation();
        });
    });

    // State shared across event handlers. `isProcessing` mirrors backend status; `eventSource`
    // is the single SSE pipe used to stream progress/log events for the active job.
    let models = [];
    let isProcessing = false;
    let eventSource = null;
    let runtimeTimer = null;
    let currentBrowsePath = "";
    let browseTarget = 'input'; // 'input', 'output', or 'viewer' — which field the file picker populates
    let detectedAccelerator = 'cpu';
    let lastManualAccelerator = 'cpu';
    const viewerPageSize = 24;
    const viewerState = {
        currentPath: '',
        images: [],
        total: 0,
        offset: 0,
        hasMore: false,
        activeIndex: 0,
        loading: false,
        savingTags: false,
        viewMode: 'grid'
    };

    // ----- Slider Progress -----

    function updateSliderProgress(input) {
        const min = parseFloat(input.min) || 0;
        const max = parseFloat(input.max) || 100;
        const val = parseFloat(input.value);
        const progress = ((val - min) / (max - min)) * 100;
        input.style.setProperty('--slider-value', `${progress}%`);
    }

    function getSelectedAccelerator() {
        return Array.from(accelRadios).find((radio) => radio.checked)?.value || null;
    }

    function formatRuntime(totalSeconds) {
        const safeSeconds = Math.max(0, Math.floor(totalSeconds));
        const hours = String(Math.floor(safeSeconds / 3600)).padStart(2, '0');
        const minutes = String(Math.floor((safeSeconds % 3600) / 60)).padStart(2, '0');
        const seconds = String(safeSeconds % 60).padStart(2, '0');
        return `${hours}:${minutes}:${seconds}`;
    }

    function renderRuntime(totalSeconds = 0) {
        runtimeClock.textContent = formatRuntime(totalSeconds);
    }

    function stopRuntimeTimer() {
        if (runtimeTimer) {
            window.clearInterval(runtimeTimer);
            runtimeTimer = null;
        }
    }

    function startRuntimeTimer(startedAtValue = new Date().toISOString()) {
        const startedAt = new Date(startedAtValue);

        stopRuntimeTimer();
        if (Number.isNaN(startedAt.getTime())) {
            renderRuntime(0);
            return;
        }

        const tick = () => renderRuntime((Date.now() - startedAt.getTime()) / 1000);
        tick();
        runtimeTimer = window.setInterval(tick, 1000);
    }

    function syncRuntimeFromStatus(statusData) {
        if (statusData.is_processing && statusData.started_at) {
            startRuntimeTimer(statusData.started_at);
            return;
        }

        if (statusData.is_processing) {
            if (!runtimeTimer) {
                startRuntimeTimer();
            }
            return;
        }

        stopRuntimeTimer();
        if (typeof statusData.runtime_seconds === 'number') {
            renderRuntime(statusData.runtime_seconds);
        }
    }

    function resetProgressForNewRun() {
        progressTitle.textContent = "Preparing";
        progressFile.textContent = "Scanning files...";
        progressPct.textContent = "0%";
        progressCounts.textContent = "0 / 0 images";
        progressBar.style.width = "0%";
        progressBar.classList.remove('bg-green-500', 'bg-yellow-500', 'bg-red-500');
        progressBar.classList.add('bg-primary');
    }

    function setSelectedAccelerator(value) {
        const availableRadio = Array.from(accelRadios).find((radio) => radio.value === value && !radio.disabled)
            || Array.from(accelRadios).find((radio) => radio.value === detectedAccelerator && !radio.disabled)
            || Array.from(accelRadios).find((radio) => !radio.disabled);

        if (availableRadio) {
            availableRadio.checked = true;
            lastManualAccelerator = availableRadio.value;
        }
    }

    function getEffectiveAccelerator() {
        return manualAccelToggle.checked
            ? (getSelectedAccelerator() || lastManualAccelerator || detectedAccelerator)
            : detectedAccelerator;
    }

    function syncAcceleratorUI() {
        if (manualAccelToggle.checked && (!getSelectedAccelerator() || document.querySelector('input[name="accel-choice"]:checked')?.disabled)) {
            setSelectedAccelerator(lastManualAccelerator);
        }

        const effectiveAccelerator = getEffectiveAccelerator();
        manualAccelStatus.textContent = manualAccelToggle.checked
            ? `enabled (${effectiveAccelerator.toUpperCase()})`
            : 'disabled';
        accelOptionsDiv.classList.toggle('hidden', !manualAccelToggle.checked);
        accelSpec.textContent = manualAccelToggle.checked
            ? `${effectiveAccelerator.toUpperCase()} (manual)`
            : detectedAccelerator.toUpperCase();
    }

    function updateViewToggle(button, active) {
        if (!button) {
            return;
        }

        button.setAttribute('aria-pressed', active ? 'true' : 'false');
        button.classList.toggle('bg-background', active);
        button.classList.toggle('text-foreground', active);
        button.classList.toggle('shadow-xs', active);
        button.classList.toggle('text-muted-foreground', !active);
    }

    function setActiveView(view) {
        const showingViewer = view === 'viewer';
        taggerView.classList.toggle('hidden', showingViewer);
        viewerView.classList.toggle('hidden', !showingViewer);
        updateViewToggle(showTaggerViewBtn, !showingViewer);
        updateViewToggle(showViewerViewBtn, showingViewer);
    }

    function getBrowseOpener() {
        if (browseTarget === 'output') {
            return outputBrowseBtn;
        }
        if (browseTarget === 'viewer') {
            return viewerBrowseBtn;
        }
        return browseBtn;
    }

    function getViewerImageUrl(path) {
        return `/api/image?path=${encodeURIComponent(path)}`;
    }

    function setViewerError(message = '') {
        viewerErrorMsg.textContent = message;
        viewerErrorMsg.classList.toggle('hidden', !message);
    }

    function setViewerEmptyState(title, description) {
        viewerEmptyState.innerHTML = `
            <p class="text-base font-semibold">${escapeHtml(title)}</p>
            <p class="mt-2 text-sm text-muted-foreground">${escapeHtml(description)}</p>
        `;
        viewerEmptyState.classList.remove('hidden');
        viewerResults.classList.add('hidden');
        viewerFooter.classList.add('hidden');
    }

    function renderViewerSummary() {
        if (!viewerState.currentPath) {
            viewerSummary.textContent = 'Choose a folder to start browsing image files and tags.';
            viewerCountBadge.textContent = '0 files';
            return;
        }

        const loadedCount = viewerState.images.length;
        const imageWord = viewerState.total === 1 ? 'image file' : 'image files';
        const scopeLabel = viewerRecursiveCheck.checked ? 'including subdirectories' : 'in this directory';
        viewerSummary.textContent = `Showing ${loadedCount} of ${viewerState.total} ${imageWord} from ${viewerState.currentPath} (${scopeLabel}).`;
        viewerCountBadge.textContent = `${viewerState.total} file${viewerState.total === 1 ? '' : 's'}`;
    }

    function setViewerLoading(loading, append = false) {
        viewerState.loading = loading;
        viewerLoadBtn.disabled = loading;
        viewerLoadMoreBtn.disabled = loading;
        viewerBrowseBtn.disabled = loading;
        viewerUseSourceBtn.disabled = loading;
        viewerRecursiveCheck.disabled = loading;
        viewerPathInput.disabled = loading;
        viewerLoadBtn.textContent = loading ? 'Loading...' : 'Load Files';
        viewerLoadMoreBtn.textContent = loading && append ? 'Loading...' : 'Load More Files';
    }

    function syncViewerLayoutToggle() {
        updateViewToggle(viewerGridModeBtn, viewerState.viewMode === 'grid');
        updateViewToggle(viewerListModeBtn, viewerState.viewMode === 'list');
    }

    function applyViewerLayout() {
        viewerResults.className = viewerState.viewMode === 'grid'
            ? 'grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4'
            : 'flex flex-col gap-3';
    }

    function renderViewerTags(item, maxVisibleTags = 4) {
        const visibleTags = item.tags.slice(0, maxVisibleTags);
        const extraTags = item.tags.length - visibleTags.length;
        const tagsMarkup = visibleTags.map((tag) => (
            `<span class="badge-secondary">${escapeHtml(tag)}</span>`
        )).join('');
        const extraTagMarkup = extraTags > 0
            ? `<span class="badge-secondary">+${extraTags} more</span>`
            : '';
        return item.tags.length > 0
            ? `${tagsMarkup}${extraTagMarkup}`
            : '<span class="text-xs text-muted-foreground">No XMP tags yet</span>';
    }

    function renderViewerGallery() {
        renderViewerSummary();
        syncViewerLayoutToggle();

        if (viewerState.images.length === 0) {
            setViewerEmptyState(
                'No supported image files found',
                'Try another folder or enable recursive browsing to search subdirectories too.'
            );
            return;
        }

        viewerEmptyState.classList.add('hidden');
        viewerResults.classList.remove('hidden');
        applyViewerLayout();
        viewerResults.innerHTML = '';

        viewerState.images.forEach((item, index) => {
            const card = document.createElement('button');
            card.type = 'button';
            card.dataset.viewerIndex = String(index);
            const tagBlock = renderViewerTags(item, viewerState.viewMode === 'grid' ? 4 : 6);

            if (viewerState.viewMode === 'grid') {
                card.className = 'group overflow-hidden rounded-xl border border-border/60 bg-background text-left shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-primary';
                card.innerHTML = `
                    <div class="aspect-[4/3] overflow-hidden bg-muted/30">
                        <img src="${getViewerImageUrl(item.path)}" alt="${escapeHtml(item.name)}"
                            class="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.02]">
                    </div>
                    <div class="space-y-3 p-4">
                        <div class="space-y-1">
                            <p class="truncate text-sm font-semibold text-foreground">${escapeHtml(item.name)}</p>
                            <p class="text-xs text-muted-foreground">${item.tag_count} tag${item.tag_count === 1 ? '' : 's'}</p>
                        </div>
                        <div class="flex flex-wrap gap-2">${tagBlock}</div>
                    </div>
                `;
            } else {
                card.className = 'group flex w-full items-start gap-4 rounded-xl border border-border/60 bg-background p-4 text-left shadow-sm transition-all hover:border-primary/40 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-primary';
                card.innerHTML = `
                    <div class="h-24 w-32 shrink-0 overflow-hidden rounded-lg bg-muted/30">
                        <img src="${getViewerImageUrl(item.path)}" alt="${escapeHtml(item.name)}"
                            class="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.02]">
                    </div>
                    <div class="min-w-0 flex-1 space-y-2">
                        <div class="flex flex-col gap-1 md:flex-row md:items-start md:justify-between">
                            <div class="min-w-0 space-y-1">
                                <p class="truncate text-sm font-semibold text-foreground">${escapeHtml(item.name)}</p>
                                <p class="truncate text-xs text-muted-foreground font-mono">${escapeHtml(item.path)}</p>
                            </div>
                            <span class="text-xs text-muted-foreground">${item.tag_count} tag${item.tag_count === 1 ? '' : 's'}</span>
                        </div>
                        <div class="flex flex-wrap gap-2">${tagBlock}</div>
                    </div>
                `;
            }

            card.addEventListener('click', () => openLightboxAt(index));
            viewerResults.appendChild(card);
        });

        viewerFooter.classList.toggle('hidden', !viewerState.hasMore);
    }

    function renderLightbox() {
        const item = viewerState.images[viewerState.activeIndex];
        if (!item) {
            return;
        }

        lightboxPosition.textContent = `${viewerState.activeIndex + 1} / ${viewerState.images.length}`;
        lightboxTagCount.textContent = `${item.tag_count} tag${item.tag_count === 1 ? '' : 's'}`;
        lightboxTitle.textContent = item.name;
        lightboxPath.textContent = item.path;
        lightboxCaption.textContent = item.xmp_exists
            ? 'Showing image preview with tags loaded from its XMP sidecar.'
            : 'Showing image preview. No XMP sidecar tags were found for this file.';
        lightboxImage.src = getViewerImageUrl(item.path);
        lightboxImage.alt = item.name;
        renderLightboxTags();
        lightboxPrevBtn.disabled = viewerState.activeIndex === 0;
        lightboxNextBtn.disabled = viewerState.activeIndex >= viewerState.images.length - 1;
    }

    // ----- Lightbox tag editing (add / rename / delete XMP keywords) -----

    function setLightboxTagError(message = '') {
        lightboxTagError.textContent = message;
        lightboxTagError.classList.toggle('hidden', !message);
    }

    function updateViewerRecordTags(index, tags) {
        const item = viewerState.images[index];
        if (!item) {
            return;
        }
        item.tags = tags.filter(Boolean);
        item.tag_count = item.tags.length;
        if (item.tags.length > 0) {
            item.xmp_exists = true;
        }
    }

    async function persistLightboxTags(path, tags) {
        const res = await fetch('/api/tags/keywords', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path, tags })
        });
        const data = await readJson(res);
        if (!res.ok) {
            throw new Error(data.detail || 'Failed to update tags.');
        }
        return data.tags || [];
    }

    async function commitLightboxTags(tags, controlEl) {
        if (viewerState.savingTags) {
            return;
        }
        const item = viewerState.images[viewerState.activeIndex];
        if (!item) {
            return;
        }

        viewerState.savingTags = true;
        if (controlEl) {
            controlEl.disabled = true;
        }
        setLightboxTagError('');

        try {
            const updated = await persistLightboxTags(item.path, tags);
            updateViewerRecordTags(viewerState.activeIndex, updated);
            renderViewerGallery();
            renderLightbox();
        } catch (error) {
            setLightboxTagError(error.message);
            renderLightboxTags();
        } finally {
            viewerState.savingTags = false;
            if (controlEl) {
                controlEl.disabled = false;
            }
        }
    }

    function lightboxTagActionButton(className, label, iconPaths, handler) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.title = label;
        btn.setAttribute('aria-label', `${label} tag`);
        btn.className = className;
        btn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${iconPaths}</svg>`;
        btn.addEventListener('click', (event) => {
            event.stopPropagation();
            handler(btn);
        });
        return btn;
    }

    function startTagRename(chip, tagIndex, original) {
        if (viewerState.savingTags || chip.querySelector('input')) {
            return;
        }

        const input = document.createElement('input');
        input.type = 'text';
        input.value = original;
        input.maxLength = 64;
        input.className = 'h-6 w-32 rounded-md border border-border bg-background px-1.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary';

        chip.replaceChildren(input);
        input.focus();
        input.select();

        const finish = () => {
            if (document.contains(input)) {
                renderLightboxTags();
            }
        };

        input.addEventListener('keydown', (event) => {
            event.stopPropagation();
            if (event.key === 'Enter') {
                event.preventDefault();
                const value = input.value.trim();
                if (!value || value === original) {
                    finish();
                    return;
                }
                const tags = viewerState.images[viewerState.activeIndex].tags.slice();
                tags[tagIndex] = value;
                commitLightboxTags(tags, input);
            } else if (event.key === 'Escape') {
                event.preventDefault();
                finish();
            }
        });
        input.addEventListener('blur', finish);
        input.addEventListener('click', (event) => event.stopPropagation());
    }

    function renderLightboxTags() {
        const item = viewerState.images[viewerState.activeIndex];
        if (!item) {
            return;
        }

        lightboxTags.innerHTML = '';
        lightboxEmptyTags.classList.toggle('hidden', item.tags.length > 0);

        item.tags.forEach((tag, tagIndex) => {
            const chip = document.createElement('span');
            chip.className = 'badge-secondary inline-flex items-center gap-1';

            const label = document.createElement('span');
            label.textContent = tag;
            chip.appendChild(label);

            chip.appendChild(lightboxTagActionButton(
                'rounded p-0.5 text-muted-foreground hover:text-foreground focus:outline-none focus-visible:ring-1 focus-visible:ring-primary',
                'Rename',
                '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/>',
                () => startTagRename(chip, tagIndex, tag)
            ));
            chip.appendChild(lightboxTagActionButton(
                'rounded p-0.5 text-muted-foreground hover:text-destructive focus:outline-none focus-visible:ring-1 focus-visible:ring-destructive',
                'Delete',
                '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
                (deleteBtn) => {
                    if (viewerState.savingTags) {
                        return;
                    }
                    const tags = viewerState.images[viewerState.activeIndex].tags.slice();
                    tags.splice(tagIndex, 1);
                    commitLightboxTags(tags, deleteBtn);
                }
            ));

            lightboxTags.appendChild(chip);
        });
    }

    function addLightboxTag() {
        if (viewerState.savingTags) {
            return;
        }
        const item = viewerState.images[viewerState.activeIndex];
        if (!item) {
            return;
        }

        const value = lightboxNewTagInput.value.trim();
        if (!value) {
            return;
        }
        if (item.tags.includes(value)) {
            setLightboxTagError(`"${value}" already exists on this image.`);
            return;
        }

        commitLightboxTags([...item.tags, value]).then(() => {
            lightboxNewTagInput.value = '';
        });
    }

    function openLightboxAt(index) {
        if (!viewerState.images[index]) {
            return;
        }

        viewerState.activeIndex = index;
        viewerState.savingTags = false;
        setLightboxTagError('');
        lightboxNewTagInput.value = '';
        renderLightbox();
        const opener = viewerResults.querySelector(`[data-viewer-index="${index}"]`) || viewerLoadBtn;
        openDialog(lightboxDialog, {
            opener,
            onClose: () => {
                lightboxImage.removeAttribute('src');
            }
        });
    }

    function moveLightbox(step) {
        const nextIndex = viewerState.activeIndex + step;
        if (!lightboxDialog.open || nextIndex < 0 || nextIndex >= viewerState.images.length) {
            return;
        }

        viewerState.activeIndex = nextIndex;
        renderLightbox();
    }

    // ----- Initialization -----

    async function init() {
        try {
            const sysRes = await fetch('/api/system');
            const data = await readJson(sysRes);
            
            models = data.models;

            // Prefill the working folders with the server's default so the
            // app opens the development sample set without manual browsing.
            if (data.default_dir) {
                if (!inputPath.value.trim()) {
                    inputPath.value = data.default_dir;
                }
                if (!viewerPathInput.value.trim()) {
                    viewerPathInput.value = data.default_dir;
                }
            }
            
            // Populate Hardware
            ramSpec.textContent = `${data.hardware.total_ram_gb} GB (${data.hardware.available_ram_gb} GB free)`;
            accelSpec.textContent = data.hardware.accelerator.toUpperCase();
            perfRating.textContent = data.performance_rating;
            
            // Animate Hardware Panel In
            setTimeout(() => {
                 hardwarePanel.classList.remove('opacity-0');
            }, 500);
            
            // Populate Models
            modelSelect.innerHTML = '';
            models.forEach(m => {
                const opt = document.createElement('option');
                opt.value = m.key;
                opt.textContent = `${m.name} ${m.supported ? '' : '(Not Recommended)'}`;
                if (!m.supported && !m.recommended) {
                    opt.disabled = true;
                }
                modelSelect.appendChild(opt);
            });
            
            updateModelWarning();

            // Set up Manual Accelerator options based on system capabilities
            const sysAccel = data.hardware.accelerator;
            detectedAccelerator = sysAccel;
            lastManualAccelerator = sysAccel;
            if (sysAccel === 'cuda') {
                accelCuda.disabled = false;
                labelCuda.classList.remove('text-muted-foreground');
                labelCuda.classList.add('text-foreground');
                accelCpu.disabled = false;
                accelCuda.checked = true;
                
                // Show tip for unavailable option
                tipMps.classList.remove('hidden');
            } else if (sysAccel === 'mps') {
                accelMps.disabled = false;
                labelMps.classList.remove('text-muted-foreground');
                labelMps.classList.add('text-foreground');
                accelCpu.disabled = false;
                accelMps.checked = true;
                
                // Show tip for unavailable option
                tipCuda.classList.remove('hidden');
            } else {
                // Only CPU
                accelCpu.disabled = false;
                accelCpu.checked = true;
                
                // Show tips for both
                tipCuda.classList.remove('hidden');
                tipMps.classList.remove('hidden');
            }

            syncAcceleratorUI();

            // If the page is refreshed mid-run, restore the locked UI and reconnect to the stream.
            const statusRes = await fetch('/api/status');
            const statusData = await readJson(statusRes);
            syncRuntimeFromStatus(statusData);
            if (statusData.is_processing) {
                setProcessingState(true);
            }

        } catch (e) {
            console.error(e);
            errorMsg.textContent = "Failed to connect to backend api.";
            errorMsg.classList.remove("hidden");
        }
    }

    init();
    updateSliderProgress(thresholdInput);
    updateSliderProgress(maxTagsInput);
    setActiveView('tagger');

    // ----- Event Listeners -----

    thresholdInput.addEventListener('input', (e) => {
        thresholdVal.textContent = e.target.value;
        updateSliderProgress(e.target);
    });

    maxTagsInput.addEventListener('input', (e) => {
        maxTagsVal.textContent = e.target.value;
        updateSliderProgress(e.target);
    });

    modelSelect.addEventListener('change', updateModelWarning);
    startBtn.addEventListener('click', startJob);
    
    stopBtn.addEventListener('click', async () => {
        stopBtn.disabled = true;
        try {
            const res = await fetch('/api/stop', { method: 'POST' });
            if (!res.ok) {
                const data = await readJson(res);
                throw new Error(data.detail || 'Failed to stop job');
            }
        } catch (e) {
            errorMsg.textContent = 'Error stopping job: ' + e.message;
            errorMsg.classList.remove('hidden');
            stopBtn.disabled = false;
        }
    });
    showTaggerViewBtn.addEventListener('click', () => setActiveView('tagger'));
    showViewerViewBtn.addEventListener('click', () => setActiveView('viewer'));

    clearLogsBtn.addEventListener('click', () => {
        logContainer.innerHTML = '';
        addLog({level: "INFO", message: "Logs cleared."});
    });

    copyLogsBtn.addEventListener('click', async () => {
        const logText = Array.from(logContainer.children)
            .map((entry) => entry.innerText.trim())
            .filter(Boolean)
            .join('\n');

        if (!logText) {
            addLog({level: "INFO", message: "No log output available to copy."});
            return;
        }

        try {
            if (navigator.clipboard?.writeText) {
                await navigator.clipboard.writeText(logText);
            } else {
                const copyBuffer = document.createElement('textarea');
                copyBuffer.value = logText;
                copyBuffer.setAttribute('readonly', '');
                copyBuffer.style.position = 'absolute';
                copyBuffer.style.left = '-9999px';
                document.body.appendChild(copyBuffer);
                copyBuffer.select();
                document.execCommand('copy');
                document.body.removeChild(copyBuffer);
            }

            addLog({level: "INFO", message: "Copied terminal output to clipboard."});
        } catch (error) {
            console.error('Failed to copy terminal output:', error);
            addLog({level: "ERROR", message: "Failed to copy terminal output to clipboard."});
        }
    });

    downloadLogBtn.addEventListener('click', () => {
        window.open('/api/logs/download', '_blank');
    });

    // Output location toggle
    outputToggle.addEventListener('change', () => {
        if (outputToggle.checked) {
            outputDirFields.classList.remove('hidden');
        } else {
            outputDirFields.classList.add('hidden');
            outputDirInput.value = '';
        }
    });

    // Manual Accelerator toggle
    manualAccelToggle.addEventListener('change', () => {
        if (manualAccelToggle.checked) {
            setSelectedAccelerator(lastManualAccelerator);
        }
        syncAcceleratorUI();
    });

    Array.from(accelRadios).forEach((radio) => {
        radio.addEventListener('change', () => {
            if (radio.checked) {
                lastManualAccelerator = radio.value;
                syncAcceleratorUI();
            }
        });
    });
    
    function syncHelpDialogState() {
        const darkToggle = document.getElementById('dark-mode-toggle');
        const darkLabel = document.getElementById('dark-mode-label');
        if (darkToggle) {
            const isDark = document.documentElement.classList.contains('dark');
            darkToggle.checked = isDark;
            if (darkLabel) darkLabel.innerHTML = isDark
                ? 'Dark mode <span class="font-medium">enabled</span>'
                : 'Light mode <span class="font-medium">enabled</span>';
        }
    }

    function openDialog(dialog, options = {}) {
        if (!dialog || dialog.open) {
            return;
        }

        const state = {
            opener: options.opener ?? document.activeElement,
            onClose: options.onClose ?? null
        };

        dialogStates.set(dialog, state);
        if (typeof options.beforeOpen === 'function') {
            options.beforeOpen();
        }
        dialog.showModal();
    }

    function cleanupDialog(dialog) {
        const state = dialogStates.get(dialog) ?? {};
        const activeElement = document.activeElement;

        if (activeElement && dialog.contains(activeElement) && typeof activeElement.blur === 'function') {
            activeElement.blur();
        }

        if (typeof state.onClose === 'function') {
            state.onClose(state);
        }

        dialogStates.delete(dialog);
    }

    function requestDialogClose(dialog) {
        if (dialog?.open) {
            dialog.close();
        }
    }

    function wireDialog(dialog, options = {}) {
        if (!dialog) {
            return;
        }

        dialog.addEventListener('click', (event) => {
            if (event.target === dialog) {
                requestDialogClose(dialog);
            }
        });

        dialog.addEventListener('cancel', (event) => {
            event.preventDefault();
            requestDialogClose(dialog);
        });

        dialog.addEventListener('close', () => cleanupDialog(dialog));

        dialog.querySelectorAll('[data-dialog-close]').forEach((button) => {
            button.addEventListener('click', () => requestDialogClose(dialog));
        });
    }

    wireDialog(helpDialog);
    wireDialog(perfDialog);
    wireDialog(accelDialog);
    wireDialog(filePickerDialog);
    wireDialog(lightboxDialog);

    // Dialog openers — native showModal()
    helpBtn.addEventListener('click', () => openDialog(helpDialog, {
        opener: helpBtn,
        beforeOpen: syncHelpDialogState,
        onClose: ({ opener }) => opener?.blur()
    }));
    accelBox.addEventListener('click', () => openDialog(accelDialog, {
        opener: accelBox,
        beforeOpen: syncAcceleratorUI
    }));
    perfBox.addEventListener('click', () => openDialog(perfDialog, { opener: perfBox }));

    // Dark mode toggle in Help dialog
    const darkModeToggle = document.getElementById('dark-mode-toggle');
    const darkModeLabel = document.getElementById('dark-mode-label');
    darkModeToggle.addEventListener('change', () => {
        const mode = darkModeToggle.checked ? 'dark' : 'light';
        if (themeController?.applyTheme) {
            themeController.applyTheme(mode);
        } else {
            document.dispatchEvent(new CustomEvent('basecoat:theme', { detail: { mode } }));
        }
        if (darkModeLabel) darkModeLabel.innerHTML = darkModeToggle.checked
            ? 'Dark mode <span class="font-medium">enabled</span>'
            : 'Light mode <span class="font-medium">enabled</span>';
    });
    
    browseBtn.addEventListener('click', () => {
        browseTarget = 'input';
        openFilePicker(inputPath.value.trim());
    });

    outputBrowseBtn.addEventListener('click', () => {
        browseTarget = 'output';
        openFilePicker(outputDirInput.value.trim());
    });

    viewerBrowseBtn.addEventListener('click', () => {
        browseTarget = 'viewer';
        openFilePicker(viewerPathInput.value.trim());
    });

    cancelFilePickerBtn.addEventListener('click', () => requestDialogClose(filePickerDialog));
    
    selectDirBtn.addEventListener('click', () => {
        if (currentBrowsePath) {
            if (browseTarget === 'output') {
                outputDirInput.value = currentBrowsePath;
            } else if (browseTarget === 'viewer') {
                viewerPathInput.value = currentBrowsePath;
            } else {
                inputPath.value = currentBrowsePath;
            }
        }
        requestDialogClose(filePickerDialog);

        if (browseTarget === 'viewer' && currentBrowsePath) {
            setActiveView('viewer');
            loadViewerDirectory();
        }
    });

    viewerLoadBtn.addEventListener('click', () => loadViewerDirectory());
    viewerLoadMoreBtn.addEventListener('click', () => loadViewerDirectory({ append: true }));
    viewerGridModeBtn.addEventListener('click', () => {
        if (viewerState.viewMode !== 'grid') {
            viewerState.viewMode = 'grid';
            renderViewerGallery();
        }
    });
    viewerListModeBtn.addEventListener('click', () => {
        if (viewerState.viewMode !== 'list') {
            viewerState.viewMode = 'list';
            renderViewerGallery();
        }
    });
    viewerUseSourceBtn.addEventListener('click', () => {
        const sourcePath = inputPath.value.trim();
        if (!sourcePath) {
            setActiveView('viewer');
            setViewerError('Choose a source folder first, or browse directly in the viewer.');
            return;
        }

        viewerPathInput.value = sourcePath;
        viewerRecursiveCheck.checked = recursiveCheck.checked;
        setActiveView('viewer');
        loadViewerDirectory();
    });
    viewerPathInput.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
            event.preventDefault();
            loadViewerDirectory();
        }
    });
    lightboxPrevBtn.addEventListener('click', () => moveLightbox(-1));
    lightboxNextBtn.addEventListener('click', () => moveLightbox(1));
    lightboxAddTagBtn.addEventListener('click', addLightboxTag);
    lightboxNewTagInput.addEventListener('keydown', (event) => {
        event.stopPropagation();
        if (event.key === 'Enter') {
            event.preventDefault();
            addLightboxTag();
        } else if (event.key === 'Escape') {
            event.preventDefault();
            requestDialogClose(lightboxDialog);
        }
    });
    document.addEventListener('keydown', (event) => {
        if (!lightboxDialog.open) {
            return;
        }
        if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) {
            return;
        }

        if (event.key === 'ArrowLeft') {
            event.preventDefault();
            moveLightbox(-1);
        } else if (event.key === 'ArrowRight') {
            event.preventDefault();
            moveLightbox(1);
        }
    });

    // ----- Functions -----

    function updateModelWarning() {
        const selected = models.find(m => m.key === modelSelect.value);
        if (selected && !selected.supported) {
            modelWarning.textContent = selected.warning;
            modelWarning.classList.remove('hidden');
        } else {
            modelWarning.classList.add('hidden');
        }
        
        // Hide threshold for VLM as they don't use it the same way CLIP does
        const thresholdGroup = thresholdInput.closest('.grid');
        if (selected && selected.type === "vlm") {
             if (thresholdGroup) thresholdGroup.style.opacity = '0.5';
             thresholdInput.disabled = true;
        } else {
             if (thresholdGroup) thresholdGroup.style.opacity = '1';
             thresholdInput.disabled = false;
        }
    }

    function openFilePicker(initialPath = "") {
        const opener = getBrowseOpener();
        openDialog(filePickerDialog, { opener });
        loadDirectory(initialPath);
    }

    async function loadDirectory(path) {
        // The browser cannot enumerate local folders directly, so the dialog proxies every step
        // through `/api/browse` and redraws from the server's constrained view of the filesystem.
        dirList.innerHTML = '<div class="p-4 text-center text-sm text-muted-foreground">Loading...</div>';
        try {
            const res = await fetch(`/api/browse?path=${encodeURIComponent(path)}`);
            const data = await readJson(res);
            
            if (!res.ok) {
                dirList.innerHTML = `<div class="p-4 text-center text-sm text-destructive">${escapeHtml(data.detail || 'Unknown error')}</div>`;
                return;
            }
            
            currentBrowsePath = data.current_path;
            currentDirPathSpan.textContent = data.current_path;

            dirList.innerHTML = '';
            if (data.items.length === 0) {
                dirList.innerHTML = '<div class="p-4 text-center text-sm text-muted-foreground">Folder is empty</div>';
                return;
            }
            
            data.items.forEach(item => {
                const btn = document.createElement('button');
                btn.className = "w-full text-left px-3 py-2 text-sm rounded-md hover:bg-muted/50 focus:bg-muted/50 focus:outline-none transition-colors flex items-center gap-3 group";
                
                let icon = '';
                if (item.name === "..") {
                    icon = `<svg class="text-muted-foreground group-hover:text-foreground transition-colors shrink-0" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6"/></svg>`;
                } else {
                    icon = `<svg class="text-blue-500/80 shrink-0" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/></svg>`;
                }
                
                btn.innerHTML = `${icon}<span class="truncate">${escapeHtml(item.name)}</span>`;
                btn.onclick = () => loadDirectory(item.path);
                dirList.appendChild(btn);
            });
            
         } catch (e) {
              dirList.innerHTML = `<div class="p-4 text-center text-sm text-destructive">Failed to load directory</div>`;
         }
    }

    async function loadViewerDirectory({ append = false } = {}) {
        if (viewerState.loading) {
            return;
        }

        const path = viewerPathInput.value.trim();
        if (!path) {
            setActiveView('viewer');
            setViewerError('Please choose a folder for the viewer.');
            return;
        }

        const offset = append ? viewerState.offset : 0;
        setActiveView('viewer');
        setViewerError('');
        setViewerLoading(true, append);

        if (!append) {
            viewerState.images = [];
            viewerState.total = 0;
            viewerState.offset = 0;
            viewerState.hasMore = false;
            viewerState.currentPath = path;
            viewerSummary.textContent = 'Loading files...';
            viewerCountBadge.textContent = 'Loading...';
            setViewerEmptyState('Loading files...', 'Gathering image previews and XMP tags for the selected folder.');
        }

        try {
            const params = new URLSearchParams({
                path,
                recursive: viewerRecursiveCheck.checked ? 'true' : 'false',
                offset: String(offset),
                limit: String(viewerPageSize)
            });
            const res = await fetch(`/api/images?${params.toString()}`);
            const data = await readJson(res);

            if (!res.ok) {
                throw new Error(data.detail || 'Failed to load images.');
            }

            viewerState.currentPath = data.current_path;
            viewerPathInput.value = data.current_path;
            viewerState.total = data.total;
            viewerState.hasMore = data.has_more;
            viewerState.offset = data.offset + data.images.length;
            if (append) {
                viewerState.images = viewerState.images.concat(data.images);
            } else {
                viewerState.images = data.images;
            }

            renderViewerGallery();
        } catch (error) {
            viewerState.images = append ? viewerState.images : [];
            viewerState.total = append ? viewerState.total : 0;
            viewerState.offset = append ? viewerState.offset : 0;
            viewerState.hasMore = append ? viewerState.hasMore : false;
            setViewerError(error.message || 'Failed to load files.');
            if (!viewerState.images.length) {
                setViewerEmptyState('Unable to load files', error.message || 'Try another folder and try again.');
                renderViewerSummary();
            }
        } finally {
            setViewerLoading(false, append);
        }
    }

    async function startJob() {
        if (isProcessing) return;
        
        const path = inputPath.value.trim();
        if (!path) {
            errorMsg.textContent = "Please provide a directory path.";
            errorMsg.classList.remove("hidden");
            return;
        }
        
        errorMsg.classList.add("hidden");
        resetProgressForNewRun();
        // Flip the UI into the running state before the POST resolves so double-submits are blocked
        // and the SSE connection is ready to receive the first progress event immediately.
        setProcessingState(true);

        try {
            const payload = {
                input: path,
                model_id: modelSelect.value,
                threshold: parseFloat(thresholdInput.value),
                max_tags: parseInt(maxTagsInput.value),
                recursive: recursiveCheck.checked,
                overwrite: overwriteCheck.checked
            };

            if (manualAccelToggle.checked) {
                payload.accelerator = getEffectiveAccelerator();
            }

            // Only send optional fields the backend should actually honor for this run.
            if (outputToggle.checked && outputDirInput.value.trim()) {
                payload.output_dir = outputDirInput.value.trim();
            }

            const res = await fetch('/api/tag', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            
            const data = await readJson(res);
            if (!res.ok) {
                throw new Error(data.detail || 'Unknown error');
            }
            
            logContainer.innerHTML = '';
            const acceleratorLabel = manualAccelToggle.checked
                ? `${payload.accelerator?.toUpperCase()} (manual)`
                : `${detectedAccelerator.toUpperCase()} (auto)`;
            addLog({level: "INFO", message: `Starting job via ${modelSelect.value} on ${acceleratorLabel}...`});
            if (data.started_at) {
                startRuntimeTimer(data.started_at);
            }

        } catch (e) {
            errorMsg.textContent = e.message;
            errorMsg.classList.remove("hidden");
            setProcessingState(false);
        }
    }

    function setProcessingState(processing) {
        // Centralize the "job is running" transition so button state, inputs, status text and SSE
        // lifecycle never drift apart when init(), startJob() or stream events toggle it.
        isProcessing = processing;
        inputPath.disabled = processing;
        modelSelect.disabled = processing;
        thresholdInput.disabled = processing;
        maxTagsInput.disabled = processing;
        recursiveCheck.disabled = processing;
        overwriteCheck.disabled = processing;

        if (processing) {
            startBtn.classList.add('hidden');
            if (stopBtn) {
                stopBtn.classList.remove('hidden');
                stopBtn.disabled = false;
            }
            
            statusText.textContent = "Running";
            statusDot.className = "w-2 h-2 rounded-full bg-green-500 animate-pulse";
            if (!runtimeTimer) {
                startRuntimeTimer();
            }
            
            connectSSE();
        } else {
            startBtn.classList.remove('hidden');
            if (stopBtn) {
                stopBtn.classList.add('hidden');
                stopBtn.disabled = false;
            }
            startBtn.disabled = false;
            
            statusText.textContent = "Idle";
            statusDot.className = "w-2 h-2 rounded-full bg-zinc-500";
            stopRuntimeTimer();
            
            if (eventSource) {
                eventSource.close();
                eventSource = null;
            }
        }
    }

    function connectSSE() {
        if (eventSource) return;
        
        eventSource = new EventSource('/api/stream');
        
        eventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);
            
            if (data.type === 'progress') {
                if (data.done) {
                    // Completion is signaled on the stream, not the original POST response.
                    setProcessingState(false);

                    const resultStatus = data.result_status || (data.total === 0 ? 'empty_scan' : 'completed');
                    progressBar.style.width = "100%";
                    progressBar.classList.remove('bg-primary', 'bg-green-500', 'bg-yellow-500', 'bg-red-500');

                    if (resultStatus === 'empty_scan') {
                        progressTitle.textContent = "No Images Found";
                        progressFile.textContent = "The selected path contains no supported image files.";
                        progressBar.classList.add('bg-yellow-500');
                    } else if (resultStatus === 'stopped') {
                        progressTitle.textContent = "Stopped";
                        progressFile.textContent = "Job was stopped by user.";
                        progressBar.classList.add('bg-yellow-500');
                    } else if (resultStatus === 'failed') {
                        progressTitle.textContent = "Failed";
                        progressFile.textContent = data.result_message || "Job failed. Check terminal output for details.";
                        progressBar.classList.add('bg-red-500');
                    } else {
                        progressTitle.textContent = "Finished";
                        progressFile.textContent = "Task complete.";
                        progressBar.classList.add('bg-green-500');
                    }
                    if (typeof data.runtime_seconds === 'number') {
                        renderRuntime(data.runtime_seconds);
                    }
                    return;
                }
                
                progressBar.classList.add('bg-primary');
                progressBar.classList.remove('bg-green-500', 'bg-yellow-500', 'bg-red-500');
                
                progressTitle.textContent = "Tagging";
                
                let fileD = data.filename.split('/').pop();
                progressFile.textContent = fileD ? `.../${fileD}` : data.filename;
                
                if (data.total > 0) {
                    const pct = Math.round((data.current / data.total) * 100);
                    progressBar.style.width = `${pct}%`;
                    progressPct.textContent = `${pct}%`;
                    progressCounts.textContent = `${data.current} / ${data.total} images`;
                }
                if (typeof data.runtime_seconds === 'number') {
                    renderRuntime(data.runtime_seconds);
                }
            } 
            else if (data.type === 'log') {
                addLog(data);
            }
            else if (data.type === 'idle') {
                // `/api/status` can reconnect us to a stale stream after a refresh; an explicit idle
                // event is the backend's way to tell the frontend that nothing is actively running.
                if(isProcessing) {
                    setProcessingState(false);
                }
            }
        };
        
        eventSource.onerror = () => {
             console.error("SSE connection lost. Reconnecting...");
        };
    }

    function addLog(data) {
        const div = document.createElement('div');
        div.className = "flex gap-3 hover:bg-zinc-100 dark:hover:bg-zinc-800/50 px-2 rounded -mx-2 transition-colors";

        let colorClass = "text-zinc-700 dark:text-zinc-400";
        if (data.level === 'WARNING') colorClass = "text-yellow-600 dark:text-yellow-500";
        if (data.level === 'ERROR' || data.level === 'CRITICAL') colorClass = "text-red-600 dark:text-red-500";
        if (data.level === 'DEBUG') colorClass = "text-zinc-500 dark:text-zinc-600";

        const time = new Date().toLocaleTimeString([], {hour12: false});

        div.innerHTML = `
            <span class="text-zinc-500 dark:text-zinc-600 shrink-0 w-16">${time}</span>
            <span class="${colorClass} shrink-0 w-12 text-xs font-semibold mt-[2px]">${escapeHtml(data.level || "LOG")}</span>
            <span class="text-zinc-800 dark:text-zinc-300 break-all whitespace-pre-wrap">${escapeHtml(data.message)}</span>
        `;        logContainer.appendChild(div);
        
        logContainer.scrollTop = logContainer.scrollHeight;
    }

});
