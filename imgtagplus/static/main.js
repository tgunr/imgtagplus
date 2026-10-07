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

    // Batch Selection Toolbar
    const batchToolbar = document.getElementById('batch-toolbar');
    const batchCountLabel = document.getElementById('batch-count');
    const batchSelectAllBtn = document.getElementById('batch-select-all-btn');
    const batchApplyOpenBtn = document.getElementById('batch-apply-open-btn');
    const batchRemoveOpenBtn = document.getElementById('batch-remove-open-btn');
    const batchClearBtn = document.getElementById('batch-clear-btn');

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
    const lightboxAutocompleteDropdown = document.getElementById('lightbox-autocomplete-dropdown');
    const lightboxAutocompleteItems = document.getElementById('lightbox-autocomplete-items');
    const lightboxBatchApplyBtn = document.getElementById('batch-apply-btn');

    // Rapid Decision Overlay Elements
    const rapidOverlayDialog = document.getElementById('rapid-overlay-dialog');
    const rapidOverlayGrid = document.getElementById('rapid-overlay-grid');
    const rapidAxisName = document.getElementById('rapid-axis-name');

    // Batch Apply Dialog Elements
    const batchApplyDialog = document.getElementById('batch-apply-dialog');
    const batchApplyDesc = document.getElementById('batch-apply-desc');
    const batchApplyConfirmBtn = document.getElementById('batch-apply-confirm-btn');
    const batchPendingBox = document.getElementById('batch-pending-tags');
    const batchTaxChips = document.getElementById('batch-tax-chips');
    const batchRemoveNote = document.getElementById('batch-remove-note');
    const batchModeRadios = document.querySelectorAll('input[name="batch-mode"]');
    const batchTagInput = document.getElementById('batch-tag-input');
    const batchAutocompleteDropdown = document.getElementById('batch-autocomplete-dropdown');
    const batchAutocompleteItems = document.getElementById('batch-autocomplete-items');

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
        viewMode: 'grid',
        selected: new Set(),
        inlineEditorIndex: null
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
            const card = document.createElement('div');
            card.dataset.viewerIndex = String(index);
            card.setAttribute('role', 'button');
            card.tabIndex = 0;
            const tagBlock = renderViewerTags(item, viewerState.viewMode === 'grid' ? 4 : 6);
            const batchControls = `
                    <div class="flex items-center gap-2 mt-2">
                        <label class="batch-select-label inline-flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer hover:text-foreground transition-colors" title="Select for batch tagging">
                            <input type="checkbox" class="batch-select-box w-3.5 h-3.5" data-viewer-index="${index}" ${viewerState.selected.has(index) ? 'checked' : ''}>
                            <span>Select</span>
                        </label>
                        <button type="button" class="inline-tag-edit-btn text-xs text-blue-600 dark:text-blue-400 hover:underline" data-viewer-index="${index}" aria-label="Edit tags inline">Quick edit</button>
                    </div>
            `;

            if (viewerState.viewMode === 'grid') {
                card.className = `group relative overflow-hidden rounded-xl border border-border/60 bg-background text-left shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-primary${viewerState.selected.has(index) ? ' batch-selected' : ''}`;
                card.innerHTML = `
                    <div class="aspect-[4/3] overflow-hidden bg-muted/30">
                        <img src="${getViewerImageUrl(item.path)}" alt="${escapeHtml(item.name)}"
                            class="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.02]">
                    </div>
                    <div class="space-y-3 p-4">
                        <div class="space-y-1">
                            <p class="truncate text-sm font-semibold text-foreground">${escapeHtml(item.name)}</p>
                            <p class="text-xs text-muted-foreground viewer-tag-count">${item.tag_count} tag${item.tag_count === 1 ? '' : 's'}</p>
                        </div>
                        <div class="tag-row flex flex-wrap gap-2">${tagBlock}</div>
                        ${batchControls}
                    </div>
                `;
            } else {
                card.className = `group relative flex w-full items-start gap-4 rounded-xl border border-border/60 bg-background p-4 text-left shadow-sm transition-all hover:border-primary/40 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-primary${viewerState.selected.has(index) ? ' batch-selected' : ''}`;
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
                            <span class="text-xs text-muted-foreground viewer-tag-count">${item.tag_count} tag${item.tag_count === 1 ? '' : 's'}</span>
                        </div>
                        <div class="tag-row flex flex-wrap gap-2">${tagBlock}</div>
                        ${batchControls}
                    </div>
                `;
            }

            card.addEventListener('click', (event) => {
                if (event.shiftKey) {
                    event.preventDefault();
                    toggleBatchSelect(index);
                    return;
                }
                if (event.target.closest('.batch-select-label') || event.target.closest('.inline-tag-edit-btn') || event.target.closest('.inline-tag-popover')) {
                    return;
                }
                openLightboxAt(index);
            });
            card.addEventListener('keydown', (event) => {
                if ((event.key === 'Enter' || event.key === ' ') && event.target === card) {
                    event.preventDefault();
                    openLightboxAt(index);
                }
            });
            viewerResults.appendChild(card);
        });

        viewerFooter.classList.toggle('hidden', !viewerState.hasMore);
    }

    function renderLightbox() {
        const item = viewerState.images[viewerState.activeIndex];
        if (!item) {
            return;
        }

        closeLightboxAutocomplete();
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
        renderTaxonomyChipStates(item);
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

    async function commitTagsAtIndex(index, tags, controlEl, errorEl = null) {
        if (viewerState.savingTags) {
            return;
        }
        const item = viewerState.images[index];
        if (!item) {
            return;
        }

        viewerState.savingTags = true;
        if (controlEl) {
            controlEl.disabled = true;
        }
        setLightboxTagError('');
        if (errorEl) {
            errorEl.textContent = '';
            errorEl.classList.add('hidden');
        }

        try {
            const updated = await persistLightboxTags(item.path, tags);
            updateViewerRecordTags(index, updated);
            refreshItemDisplays(index);
        } catch (error) {
            setLightboxTagError(error.message);
            if (errorEl) {
                errorEl.textContent = error.message;
                errorEl.classList.remove('hidden');
            }
        } finally {
            viewerState.savingTags = false;
            if (controlEl) {
                controlEl.disabled = false;
            }
        }
    }

    async function commitLightboxTags(tags, controlEl) {
        await commitTagsAtIndex(viewerState.activeIndex, tags, controlEl);
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

    // =====================================================================
    // Rapid tagging suite: Quick-Chips, Rapid Key-Decision overlay, Smart
    // Autocomplete, Batch Apply, Inline Tag Editor. All taxonomy writes go
    // through /api/tags/user (axis attribution) plus a keyword union in the
    // XMP sidecar so DAM tools see the human label immediately.
    // =====================================================================

    const AXIS_CHIP_CONTAINER_IDS = {
        process: 'taxonomy-chips-process',
        geometry_kind: 'taxonomy-chips-geometry',
        material_family: 'taxonomy-chips-material',
        machine_context: 'taxonomy-chips-machine',
        output_intent: 'taxonomy-chips-output'
    };
    const AXIS_HOTKEYS = { p: 'process', g: 'geometry_kind', m: 'material_family', c: 'machine_context', o: 'output_intent' };

    let rapidAxis = null;
    let batchMode = 'add';
    let pendingBatchRecords = [];
    let activeAutocompletes = [];

    // Taxonomy fetched from /api/taxonomy; axisDefByKey maps axis -> (key -> label).
    let taxonomyAxes = [];
    const axisDefByKey = new Map();

    function closeLightboxAutocomplete() {
        if (lightboxAutocompleteDropdown) {
            lightboxAutocompleteDropdown.classList.add('hidden');
        }
    }

    // ----- Smart Autocomplete -----

    function buildAutocomplete(inputEl, dropdownEl, itemsEl, options = {}) {
        const state = { items: [], activeIndex: -1 };
        const currentImage = () => viewerState.images[viewerState.activeIndex];
        const excludeLabels = () => {
            if (options.excludeFrom === 'batch') return pendingBatchRecords.map((r) => r.label);
            const item = currentImage();
            return item ? item.tags : [];
        };

        const close = () => {
            dropdownEl.classList.add('hidden');
            state.items = [];
            state.activeIndex = -1;
        };

        function renderDropdown() {
            const query = inputEl.value;
            const exclude = new Set(excludeLabels());
            state.items = getSuggestions(query, exclude);
            if (!query.trim() && options.showRecentsOnEmpty) {
                const seen = new Set(exclude);
                state.items = recentTagList
                    .filter((label) => !seen.has(label.toLowerCase()))
                    .slice(0, 6)
                    .map((label) => ({ label, source: 'recent' }));
            }
            state.activeIndex = state.items.length ? 0 : -1;
            if (!state.items.length) {
                close();
                return;
            }
            itemsEl.innerHTML = state.items.map((item, i) => `
                <button type="button" class="autocomplete-item${i === state.activeIndex ? ' is-highlighted' : ''}" data-ac-index="${i}" data-source="${item.source}">
                    <span class="ac-source" data-source="${item.source}">${escapeHtml(item.source === 'taxonomy' ? (options.axisShortLabels?.[item.axis] || 'taxonomy') : item.source)}</span>
                    <span class="ac-label">${highlightMatch(item.label, query)}</span>
                </button>
            `).join('');
            dropdownEl.classList.remove('hidden');
        }

        function setActive(index) {
            if (!state.items.length) return;
            state.activeIndex = (index + state.items.length) % state.items.length;
            itemsEl.querySelectorAll('.autocomplete-item').forEach((el, i) => {
                el.classList.toggle('is-highlighted', i === state.activeIndex);
            });
            const active = itemsEl.querySelector('.autocomplete-item.is-highlighted');
            if (active) active.scrollIntoView({ block: 'nearest' });
        }

        async function pick(index) {
            const item = state.items[index];
            if (!item) return;
            close();
            if (typeof options.onPick === 'function') {
                await options.onPick(item);
            }
        }

        inputEl.addEventListener('input', renderDropdown);
        inputEl.addEventListener('focus', renderDropdown);
        inputEl.addEventListener('keydown', (event) => {
            if (event.key === 'ArrowDown') {
                event.preventDefault();
                setActive(state.activeIndex + 1);
            } else if (event.key === 'ArrowUp') {
                event.preventDefault();
                setActive(state.activeIndex - 1);
            } else if (event.key === 'Enter') {
                event.preventDefault();
                event.stopPropagation();
                if (state.activeIndex >= 0 && dropdownEl && !dropdownEl.classList.contains('hidden')) {
                    pick(state.activeIndex);
                } else if (typeof options.onEmptySubmit === 'function') {
                    options.onEmptySubmit();
                }
            } else if (event.key === 'Escape') {
                event.preventDefault();
                event.stopPropagation();
                close();
            } else if (event.key === 'Tab' && state.activeIndex >= 0 && !dropdownEl.classList.contains('hidden')) {
                event.preventDefault();
                pick(state.activeIndex);
            }
        });

        itemsEl.addEventListener('mousedown', (event) => {
            const button = event.target.closest('.autocomplete-item');
            if (!button) return;
            event.preventDefault();
            pick(parseInt(button.dataset.acIndex, 10));
        });

        activeAutocompletes.push({ inputEl, dropdownEl, close, dispose: () => close() });
        return { close, state };
    }

    document.addEventListener('click', (event) => {
        activeAutocompletes.forEach((ac) => {
            if (!ac.inputEl.contains(event.target) && !ac.dropdownEl.contains(event.target)) {
                ac.close();
            }
        });
    });

    // Escape first closes an open suggestion dropdown instead of the whole dialog.
    document.addEventListener('keydown', (event) => {
        if (event.key !== 'Escape') return;
        const ac = activeAutocompletes.find((a) =>
            a.dropdownEl && !a.dropdownEl.classList.contains('hidden')
            && (a.inputEl === document.activeElement || a.dropdownEl.contains(document.activeElement)));
        if (ac) {
            event.preventDefault();
            event.stopPropagation();
            ac.close();
        }
    }, true);

    // ----- Taxonomy Quick-Chips (lightbox sidebar) -----

    function buildTaxonomyChips() {
        taxonomyAxes.forEach((axisDef) => {
            const container = document.getElementById(AXIS_CHIP_CONTAINER_IDS[axisDef.axis]);
            if (!container) return;
            container.innerHTML = axisDef.values.map((value) => `
                <button type="button" class="tax-chip" data-axis="${axisDef.axis}" data-key="${value.key}" title="Apply ${escapeHtml(value.label)} to the current image">
                    ${escapeHtml(value.label)}
                </button>
            `).join('');
        });
    }

    function renderTaxonomyChipStates(item) {
        const tags = new Set((item?.tags || []).map((t) => t.toLowerCase()));
        document.querySelectorAll('#taxonomy-quick-chips .tax-chip').forEach((chip) => {
            const label = axisValueLabel(chip.dataset.axis, chip.dataset.key);
            chip.classList.toggle('is-active', tags.has(label.toLowerCase()));
        });
    }

    async function putUserTaxonomyTag(path, axis, key) {
        const send = () => fetch('/api/tags/user', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path, axis, key })
        });
        let res = await send();
        if (res.status === 429) {
            // Server rate-limits taxonomy writes (60 / 10s); wait out the window once.
            await new Promise((resolve) => setTimeout(resolve, 1100));
            res = await send();
        }
        const data = await readJson(res);
        if (!res.ok) {
            throw new Error(data.detail || `Failed to record ${axis} tag.`);
        }
        return data;
    }

    async function applyAxisTagToIndex(index, axis, key) {
        const item = viewerState.images[index];
        if (!item || viewerState.savingTags) return;
        const label = axisValueLabel(axis, key);
        viewerState.savingTags = true;
        setLightboxTagError('');
        try {
            await putUserTaxonomyTag(item.path, axis, key);
            if (!item.tags.some((t) => t.toLowerCase() === label.toLowerCase())) {
                const updated = await persistLightboxTags(item.path, [...item.tags, label]);
                updateViewerRecordTags(index, updated);
            }
            addRecentTag(label);
            refreshItemDisplays(index);
        } catch (error) {
            setLightboxTagError(error.message);
        } finally {
            viewerState.savingTags = false;
        }
    }

    async function toggleAxisChip(chip) {
        const item = viewerState.images[viewerState.activeIndex];
        if (!item) return;
        const label = axisValueLabel(chip.dataset.axis, chip.dataset.key);
        if (item.tags.some((t) => t.toLowerCase() === label.toLowerCase())) {
            const tags = item.tags.filter((t) => t.toLowerCase() !== label.toLowerCase());
            await commitTagsAtIndex(viewerState.activeIndex, tags);
            return;
        }
        await applyAxisTagToIndex(viewerState.activeIndex, chip.dataset.axis, chip.dataset.key);
    }

    // ----- Rapid Key-Decision overlay -----

    function openRapidOverlay(axis) {
        const axisDef = taxonomyAxes.find((a) => a.axis === axis);
        if (!axisDef) return;
        rapidAxis = axis;
        rapidAxisName.textContent = `— ${axisDef.label}`;
        rapidOverlayGrid.innerHTML = axisDef.values.map((value, i) => `
            <button type="button" class="rapid-option" data-key="${value.key}" title="${escapeHtml(value.label)}">
                <span class="rapid-key">${i < 9 ? i + 1 : '•'}</span>
                <span class="rapid-value">${escapeHtml(value.label)}</span>
            </button>
        `).join('');
        rapidOverlayGrid.querySelectorAll('.rapid-option').forEach((btn) => {
            btn.addEventListener('click', async () => {
                requestDialogClose(rapidOverlayDialog);
                await applyAxisTagToIndex(viewerState.activeIndex, axis, btn.dataset.key);
            });
        });
        openDialog(rapidOverlayDialog, { opener: document.activeElement });
    }

    // ----- Inline Tag Editor (gallery popover, no lightbox needed) -----

    function closeInlineEditor() {
        if (viewerState.inlineEditorIndex === null) return;
        viewerState.inlineEditorIndex = null;
        document.querySelector('.inline-tag-popover')?.remove();
        activeAutocompletes = activeAutocompletes.filter((ac) => document.contains(ac.inputEl));
        renderViewerGallery();
    }

    function renderInlineEditorTags(index, panel) {
        const item = viewerState.images[index];
        if (!item) return;
        const list = panel.querySelector('.inline-tags');
        list.innerHTML = '';
        if (!item.tags.length) {
            list.innerHTML = '<span class="text-xs text-muted-foreground">No tags yet.</span>';
        }
        item.tags.forEach((tag, tagIndex) => {
            const chip = document.createElement('span');
            chip.className = 'badge-secondary inline-flex items-center gap-1';
            const label = document.createElement('span');
            label.textContent = tag;
            chip.appendChild(label);
            const remove = document.createElement('button');
            remove.type = 'button';
            remove.className = 'rounded p-0.5 text-muted-foreground hover:text-destructive';
            remove.setAttribute('aria-label', `Remove tag ${tag}`);
            remove.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>';
            remove.addEventListener('click', async (event) => {
                event.stopPropagation();
                const tags = viewerState.images[index].tags.slice();
                tags.splice(tagIndex, 1);
                await commitTagsAtIndex(index, tags, null, panel.querySelector('.inline-tag-error'));
            });
            chip.appendChild(remove);
            list.appendChild(chip);
        });
    }

    function openInlineTagEditor(card, index) {
        if (viewerState.inlineEditorIndex === index) {
            closeInlineEditor();
            return;
        }
        closeInlineEditor();

        const item = viewerState.images[index];
        if (!item) return;

        const panel = document.createElement('div');
        panel.className = 'inline-tag-popover inline-tag-editor fixed z-50 w-72 rounded-xl border border-border bg-background p-3 shadow-xl space-y-2';
        panel.innerHTML = `
            <div class="flex items-center justify-between gap-2">
                <span class="truncate text-xs font-semibold">${escapeHtml(item.name)}</span>
                <button type="button" class="inline-close btn-sm-ghost h-6 px-1" aria-label="Close editor">✕</button>
            </div>
            <div class="inline-tags flex max-h-32 flex-wrap gap-1.5 overflow-y-auto"></div>
            <div class="inline-tag-error text-xs text-destructive hidden"></div>
            <div class="relative">
                <input type="text" class="input text-xs w-full" placeholder="Add tag (type to search)…" maxlength="64" autocomplete="off">
                <div class="dropdown hidden absolute left-0 right-0 top-full mt-1 z-50 max-h-48 overflow-y-auto overflow-hidden rounded-lg border border-border bg-background shadow-xl text-sm">
                    <div class="items"></div>
                </div>
            </div>
            <p class="text-[10px] text-muted-foreground">Changes save instantly to the XMP sidecar.</p>
        `;
        document.body.appendChild(panel);

        const rect = card.getBoundingClientRect();
        const panelWidth = 288;
        let left = Math.min(rect.left, window.innerWidth - panelWidth - 12);
        left = Math.max(8, left);
        let top = rect.bottom + 6;
        const panelHeight = 260;
        if (top + panelHeight > window.innerHeight) {
            top = Math.max(8, rect.top - panelHeight - 6);
        }
        panel.style.left = `${left}px`;
        panel.style.top = `${top}px`;

        viewerState.inlineEditorIndex = index;
        renderInlineEditorTags(index, panel);

        const input = panel.querySelector('input');
        const dropdown = panel.querySelector('.dropdown');
        const itemsBox = panel.querySelector('.items');
        buildAutocomplete(input, dropdown, itemsBox, {
            showRecentsOnEmpty: true,
            onPick: async (suggestion) => {
                if (suggestion.source === 'taxonomy' && suggestion.axis) {
                    await applyAxisTagToIndex(index, suggestion.axis, suggestion.key);
                } else {
                    if (!viewerState.images[index].tags.includes(suggestion.label)) {
                        await commitTagsAtIndex(index, [...viewerState.images[index].tags, suggestion.label], null, panel.querySelector('.inline-tag-error'));
                    }
                    addRecentTag(suggestion.label);
                }
                input.value = '';
                renderInlineEditorTags(index, panel);
            },
            onEmptySubmit: async () => {
                const value = input.value.trim();
                if (!value) return;
                if (viewerState.images[index].tags.includes(value)) return;
                await commitTagsAtIndex(index, [...viewerState.images[index].tags, value], null, panel.querySelector('.inline-tag-error'));
                addRecentTag(value);
                input.value = '';
                renderInlineEditorTags(index, panel);
            }
        });

        panel.addEventListener('click', (event) => event.stopPropagation());
        panel.querySelector('.inline-close').addEventListener('click', (event) => {
            event.stopPropagation();
            closeInlineEditor();
        });
        input.focus();

        const closer = (event) => {
            if (panel.contains(event.target) || event.target.closest('.inline-tag-edit-btn')) return;
            closeInlineEditor();
        };
        document.addEventListener('mousedown', closer);
        const scrollCloser = () => closeInlineEditor();
        window.addEventListener('scroll', scrollCloser, { once: true, passive: true });
        const cleanupObserver = new MutationObserver(() => {
            if (!document.contains(panel)) {
                document.removeEventListener('mousedown', closer);
                cleanupObserver.disconnect();
            }
        });
        cleanupObserver.observe(document.body, { childList: true });
    }

    // ----- Batch selection + Batch Apply -----

    function toggleBatchSelect(index) {
        if (viewerState.selected.has(index)) {
            viewerState.selected.delete(index);
        } else {
            viewerState.selected.add(index);
        }
        syncBatchSelectionUI();
    }

    function syncBatchSelectionUI() {
        const count = viewerState.selected.size;
        viewerResults.querySelectorAll('.batch-select-box').forEach((box) => {
            const idx = parseInt(box.dataset.viewerIndex, 10);
            box.checked = viewerState.selected.has(idx);
            box.closest('.group')?.classList.toggle('batch-selected', viewerState.selected.has(idx));
        });
        if (batchToolbar) {
            batchToolbar.classList.toggle('hidden', count === 0);
        }
        if (batchCountLabel) {
            batchCountLabel.textContent = `${count} image${count === 1 ? '' : 's'} selected`;
        }
    }

    function getBatchMode() {
        const checked = Array.from(batchModeRadios).find((radio) => radio.checked);
        return checked?.value === 'remove' ? 'remove' : 'add';
    }

    function renderBatchPending() {
        if (!batchPendingBox) return;
        if (!pendingBatchRecords.length) {
            batchPendingBox.innerHTML = '<span class="text-xs text-muted-foreground">No tags queued yet — pick suggestions or taxonomy chips below.</span>';
            return;
        }
        batchPendingBox.innerHTML = '';
        pendingBatchRecords.forEach((record, i) => {
            const chip = document.createElement('span');
            chip.className = 'badge-secondary inline-flex items-center gap-1';
            const label = document.createElement('span');
            label.textContent = record.type === 'axis' ? `${axisValueLabel(record.axis, record.key)} (${record.axis.replace('_', ' ')})` : record.label;
            chip.appendChild(label);
            const remove = document.createElement('button');
            remove.type = 'button';
            remove.className = 'rounded p-0.5 text-muted-foreground hover:text-destructive';
            remove.setAttribute('aria-label', 'Remove queued tag');
            remove.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>';
            remove.addEventListener('click', () => {
                pendingBatchRecords.splice(i, 1);
                renderBatchPending();
            });
            chip.appendChild(remove);
            batchPendingBox.appendChild(chip);
        });
    }

    function buildBatchTaxChips() {
        if (!batchTaxChips) return;
        batchTaxChips.innerHTML = taxonomyAxes.map((axisDef) => `
            <div class="space-y-1.5">
                <p class="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">${escapeHtml(axisDef.label)}</p>
                <div class="flex flex-wrap gap-1.5">
                    ${axisDef.values.map((value) => `
                        <button type="button" class="tax-chip" data-axis="${axisDef.axis}" data-key="${value.key}">${escapeHtml(value.label)}</button>
                    `).join('')}
                </div>
            </div>
        `).join('');
        batchTaxChips.querySelectorAll('.tax-chip').forEach((chip) => {
            chip.addEventListener('click', () => {
                const axis = chip.dataset.axis;
                const key = chip.dataset.key;
                if (pendingBatchRecords.some((r) => r.type === 'axis' && r.axis === axis && r.key === key)) return;
                pendingBatchRecords.push({ type: 'axis', axis, key, label: axisValueLabel(axis, key) });
                renderBatchPending();
            });
        });
    }

    function openBatchApplyDialog(mode) {
        if (!viewerState.selected.size) {
            setActiveView('viewer');
            setViewerError('Select at least one image (checkbox or Shift+click) to batch-apply tags.');
            return;
        }
        batchMode = mode === 'remove' ? 'remove' : 'add';
        pendingBatchRecords = [];
        const checkedRadio = Array.from(batchModeRadios).find((radio) => radio.value === batchMode);
        if (checkedRadio) checkedRadio.checked = true;
        syncBatchModeUI();
        renderBatchPending();
        if (batchApplyDesc) {
            batchApplyDesc.textContent = `${viewerState.selected.size} image${viewerState.selected.size === 1 ? '' : 's'} selected. ${
                batchMode === 'add'
                    ? 'Queued tags are merged into each image\u2019s XMP keywords; taxonomy picks also update the axis record.'
                    : 'Queued tags are removed from each selected image\u2019s XMP keywords.'
            }`;
        }
        if (batchTagInput) batchTagInput.value = '';
        openDialog(batchApplyDialog, { opener: batchApplyOpenBtn || document.activeElement });
    }

    function syncBatchModeUI() {
        if (batchRemoveNote) {
            batchRemoveNote.classList.toggle('hidden', batchMode !== 'remove');
        }
    }

    async function runBatchApply() {
        if (!pendingBatchRecords.length || !viewerState.selected.size) {
            return;
        }
        const indices = Array.from(viewerState.selected).filter((i) => viewerState.images[i]);
        const records = pendingBatchRecords.slice();
        const removeLabels = new Set(records.map((r) => r.label.toLowerCase()));
        const axisRecords = records.filter((r) => r.type === 'axis');
        const failures = [];

        batchApplyConfirmBtn.disabled = true;
        const originalLabel = batchApplyConfirmBtn.textContent;
        batchApplyConfirmBtn.textContent = 'Applying…';

        for (const [done, index] of indices.entries()) {
            batchApplyConfirmBtn.textContent = `Applying ${done + 1}/${indices.length}…`;
            const item = viewerState.images[index];
            try {
                if (batchMode === 'add') {
                    for (const record of axisRecords) {
                        await putUserTaxonomyTag(item.path, record.axis, record.key);
                    }
                    const merged = new Set(item.tags);
                    records.forEach((r) => merged.add(r.label));
                    if (merged.size !== item.tags.length) {
                        const updated = await persistLightboxTags(item.path, Array.from(merged));
                        updateViewerRecordTags(index, updated);
                        records.forEach((r) => addRecentTag(r.label));
                    }
                } else {
                    const remaining = item.tags.filter((t) => !removeLabels.has(t.toLowerCase()));
                    if (remaining.length !== item.tags.length) {
                        const updated = await persistLightboxTags(item.path, remaining);
                        updateViewerRecordTags(index, updated);
                    }
                }
            } catch (error) {
                failures.push(`${item.name}: ${error.message}`);
            }
            if (batchMode === 'add' && axisRecords.length && indices.length > 12) {
                // Pace writes so batches stay under the server's 60-writes/10s rate limit.
                await new Promise((resolve) => setTimeout(resolve, 150));
            }
        }

        batchApplyConfirmBtn.disabled = false;
        batchApplyConfirmBtn.textContent = originalLabel;
        viewerState.selected.clear();
        requestDialogClose(batchApplyDialog);
        renderViewerGallery();
        syncBatchSelectionUI();
        if (failures.length) {
            setViewerError(`Batch apply finished with ${failures.length} error(s): ${failures[0]}${failures.length > 1 ? ` (+${failures.length - 1} more)` : ''}`);
        }
    }

    // ----- Targeted refresh after a per-image tag commit -----

    function refreshItemDisplays(index) {
        const item = viewerState.images[index];
        if (!item) return;

        const card = viewerResults.querySelector(`[data-viewer-index="${index}"]`);
        if (card) {
            const row = card.querySelector('.tag-row');
            if (row) {
                row.innerHTML = renderViewerTags(item, viewerState.viewMode === 'grid' ? 4 : 6);
            }
            const count = card.querySelector('.viewer-tag-count');
            if (count) {
                count.textContent = `${item.tag_count} tag${item.tag_count === 1 ? '' : 's'}`;
            }
        }

        if (viewerState.inlineEditorIndex === index) {
            const panel = document.querySelector('.inline-tag-popover');
            if (panel) renderInlineEditorTags(index, panel);
        }

        if (lightboxDialog.open && viewerState.activeIndex === index) {
            lightboxTagCount.textContent = `${item.tag_count} tag${item.tag_count === 1 ? '' : 's'}`;
            renderLightboxTags();
            renderTaxonomyChipStates(item);
        }
    }

    // ----- Taxonomy fetch (server is source of truth) -----

    async function loadTaxonomyFromServer() {
        try {
            const res = await fetch('/api/taxonomy');
            const data = await readJson(res);
            const axes = data?.taxonomy?.axes;
            if (!Array.isArray(axes) || !axes.length) return;
            taxonomyAxes = axes.map((axisDef) => ({
                axis: axisDef.axis,
                label: axisDef.label || titleizeKey(axisDef.axis),
                values: (axisDef.values || []).map((value) => (
                    typeof value === 'string' ? { key: value, label: titleizeKey(value) } : { key: value.key, label: value.label || titleizeKey(value.key) }
                ))
            }));
            axisDefByKey.clear();
            taxonomyAxes.forEach((axisDef) => {
                axisDefByKey.set(axisDef.axis, new Map(axisDef.values.map((value) => [value.key, value.label])));
            });
            buildTaxonomyChips();
            buildBatchTaxChips();
            if (lightboxDialog.open) {
                renderTaxonomyChipStates(viewerState.images[viewerState.activeIndex]);
            }
        } catch (_) { /* keep the built-in fallback mirror */ }
    }

    // ----- Rapid suite wiring -----

    document.getElementById('taxonomy-quick-chips')?.addEventListener('click', (event) => {
        const chip = event.target.closest('.tax-chip');
        if (!chip) return;
        event.preventDefault();
        toggleAxisChip(chip);
    });

    document.addEventListener('keydown', (event) => {
        if (rapidOverlayDialog?.open) {
            const digit = parseInt(event.key, 10);
            if (!Number.isNaN(digit)) {
                const optionIndex = digit === 0 ? 9 : digit - 1;
                const options = rapidOverlayGrid.querySelectorAll('.rapid-option');
                if (options[optionIndex]) {
                    event.preventDefault();
                    const axis = rapidAxis;
                    const key = options[optionIndex].dataset.key;
                    requestDialogClose(rapidOverlayDialog);
                    applyAxisTagToIndex(viewerState.activeIndex, axis, key);
                }
            }
            return;
        }

        if (!lightboxDialog.open || batchApplyDialog?.open) return;
        if (event.ctrlKey || event.metaKey || event.altKey) return;
        if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;

        const key = event.key.toLowerCase();
        if (AXIS_HOTKEYS[key]) {
            event.preventDefault();
            openRapidOverlay(AXIS_HOTKEYS[key]);
            return;
        }
        if (key === '/' || key === 'a') {
            event.preventDefault();
            lightboxNewTagInput.focus();
            lightboxNewTagInput.select();
            return;
        }
        if (key === 'n' && !event.shiftKey) {
            event.preventDefault();
            moveLightbox(1);
        } else if (key === 'b') {
            event.preventDefault();
            moveLightbox(-1);
        }
    });

    viewerResults.addEventListener('change', (event) => {
        const box = event.target.closest('.batch-select-box');
        if (!box) return;
        const idx = parseInt(box.dataset.viewerIndex, 10);
        if (box.checked) {
            viewerState.selected.add(idx);
        } else {
            viewerState.selected.delete(idx);
        }
        syncBatchSelectionUI();
    });

    viewerResults.addEventListener('click', (event) => {
        const editBtn = event.target.closest('.inline-tag-edit-btn');
        if (!editBtn) return;
        event.preventDefault();
        event.stopPropagation();
        const idx = parseInt(editBtn.dataset.viewerIndex, 10);
        const card = viewerResults.querySelector(`[data-viewer-index="${idx}"]`);
        if (card) openInlineTagEditor(card, idx);
    });

    batchSelectAllBtn?.addEventListener('click', () => {
        viewerState.images.forEach((_, index) => viewerState.selected.add(index));
        syncBatchSelectionUI();
    });
    batchClearBtn?.addEventListener('click', () => {
        viewerState.selected.clear();
        syncBatchSelectionUI();
    });
    batchApplyOpenBtn?.addEventListener('click', () => openBatchApplyDialog('add'));
    batchRemoveOpenBtn?.addEventListener('click', () => openBatchApplyDialog('remove'));
    lightboxBatchApplyBtn?.addEventListener('click', () => {
        if (!viewerState.selected.size) {
            setLightboxTagError('No images selected for batch apply. Close the viewer and select thumbnails first.');
            return;
        }
        openBatchApplyDialog('add');
    });
    batchApplyConfirmBtn?.addEventListener('click', () => runBatchApply());
    Array.from(batchModeRadios || []).forEach((radio) => {
        radio.addEventListener('change', () => {
            batchMode = getBatchMode();
            syncBatchModeUI();
        });
    });

    buildTaxonomyChips();
    buildBatchTaxChips();
    loadTaxonomyFromServer();

    // Smart Autocomplete Bar inside the Batch Apply dialog.
    if (batchTagInput) {
        buildAutocomplete(batchTagInput, batchAutocompleteDropdown, batchAutocompleteItems, {
            showRecentsOnEmpty: true,
            excludeFrom: 'batch',
            onPick: (suggestion) => {
                if (suggestion.source === 'taxonomy' && suggestion.axis) {
                    if (!pendingBatchRecords.some((r) => r.type === 'axis' && r.axis === suggestion.axis && r.key === suggestion.key)) {
                        pendingBatchRecords.push({ type: 'axis', axis: suggestion.axis, key: suggestion.key, label: suggestion.label });
                    }
                } else if (!pendingBatchRecords.some((r) => r.type === 'keyword' && r.label.toLowerCase() === suggestion.label.toLowerCase())) {
                    pendingBatchRecords.push({ type: 'keyword', label: suggestion.label });
                }
                addRecentTag(suggestion.label);
                renderBatchPending();
                batchTagInput.value = '';
                batchTagInput.focus();
            },
            onEmptySubmit: () => {
                const value = batchTagInput.value.trim();
                if (!value) return;
                if (!pendingBatchRecords.some((r) => r.label.toLowerCase() === value.toLowerCase())) {
                    pendingBatchRecords.push({ type: 'keyword', label: value });
                }
                addRecentTag(value);
                renderBatchPending();
                batchTagInput.value = '';
            }
        });
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
    wireDialog(rapidOverlayDialog);
    wireDialog(batchApplyDialog);

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

    // Smart Autocomplete Bar on the lightbox tag input.
    buildAutocomplete(lightboxNewTagInput, lightboxAutocompleteDropdown, lightboxAutocompleteItems, {
        showRecentsOnEmpty: true,
        onPick: async (suggestion) => {
            if (viewerState.savingTags) return;
            const item = viewerState.images[viewerState.activeIndex];
            if (!item) return;
            if (suggestion.source === 'taxonomy' && suggestion.axis) {
                await applyAxisTagToIndex(viewerState.activeIndex, suggestion.axis, suggestion.key);
            } else if (!item.tags.includes(suggestion.label)) {
                await commitLightboxTags([...item.tags, suggestion.label]);
                addRecentTag(suggestion.label);
            }
            lightboxNewTagInput.value = '';
        },
        onEmptySubmit: () => addLightboxTag()
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
            viewerState.selected.clear();
            closeInlineEditor();
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
