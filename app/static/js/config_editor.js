// Constants
const SENSITIVE_INPUT_CLASS = "sensitive-input";
const ARRAY_ITEM_CLASS = "array-item";
const ARRAY_INPUT_CLASS = "array-input";
const MAP_ITEM_CLASS = "map-item";
const MAP_KEY_INPUT_CLASS = "map-key-input";
const MAP_VALUE_INPUT_CLASS = "map-value-input";
const CUSTOM_HEADER_ITEM_CLASS = "custom-header-item";
const CUSTOM_HEADER_KEY_INPUT_CLASS = "custom-header-key-input";
const CUSTOM_HEADER_VALUE_INPUT_CLASS = "custom-header-value-input";
const SHOW_CLASS = "show"; // For modals
const API_KEY_REGEX = /AIzaSy\S{33}/g;
const VERTEX_API_KEY_REGEX = /AQ\.[a-zA-Z0-9_\-]{50}/g; // 新增 Vertex Express API Key 正则
const MASKED_VALUE = "••••••••";

// API Keys Pagination Constants
const API_KEYS_PER_PAGE = 20; // 每页显示的API密钥数量
let currentApiKeyPage = 1;
let totalApiKeyPages = 1;
let allApiKeys = []; // 存储所有API密钥数据
let filteredApiKeys = []; // 存储过滤后的API密钥数据

// DOM Elements - Global Scope for frequently accessed elements
const apiKeyModal = document.getElementById("apiKeyModal");
const apiKeyBulkInput = document.getElementById("apiKeyBulkInput");
const apiKeySearchInput = document.getElementById("apiKeySearchInput");
const bulkDeleteApiKeyModal = document.getElementById("bulkDeleteApiKeyModal");
const bulkDeleteApiKeyInput = document.getElementById("bulkDeleteApiKeyInput");
const resetConfirmModal = document.getElementById("resetConfirmModal");
const configForm = document.getElementById("configForm"); // Added for frequent use

// Vertex Express API Key Modal Elements
const vertexApiKeyModal = document.getElementById("vertexApiKeyModal");
const vertexApiKeyBulkInput = document.getElementById("vertexApiKeyBulkInput");
const bulkDeleteVertexApiKeyModal = document.getElementById(
  "bulkDeleteVertexApiKeyModal"
);
const bulkDeleteVertexApiKeyInput = document.getElementById(
  "bulkDeleteVertexApiKeyInput"
);

// Model Helper Modal Elements
const modelHelperModal = document.getElementById("modelHelperModal");
const modelHelperTitleElement = document.getElementById("modelHelperTitle");
const modelHelperSearchInput = document.getElementById(
  "modelHelperSearchInput"
);
const modelHelperListContainer = document.getElementById(
  "modelHelperListContainer"
);
const closeModelHelperModalBtn = document.getElementById(
  "closeModelHelperModalBtn"
);
const cancelModelHelperBtn = document.getElementById("cancelModelHelperBtn");

let cachedModelsList = null;
let currentModelHelperTarget = null; // { type: 'input'/'array', target: elementOrIdOrKey }

// Modal Control Functions
function openModal(modalElement) {
  if (modalElement) {
    modalElement.classList.add(SHOW_CLASS);
  }
}

function closeModal(modalElement) {
  if (modalElement) {
    modalElement.classList.remove(SHOW_CLASS);
  }
}

document.addEventListener("DOMContentLoaded", function () {
  // Initialize configuration
  initConfig();

  // Tab switching
  const tabButtons = document.querySelectorAll(".tab-btn");
  tabButtons.forEach((button) => {
    button.addEventListener("click", function (e) {
      e.stopPropagation();
      const tabId = this.getAttribute("data-tab");
      switchTab(tabId);
    });
  });

  // 检查间隔小时数输入控制
  const checkIntervalInput = document.getElementById("CHECK_INTERVAL_HOURS");
  if (checkIntervalInput) {
    checkIntervalInput.addEventListener("input", function () {
      let value = parseFloat(this.value);
      if (isNaN(value) || value < 0) {
        this.value = 0;
      }
    });
    
    checkIntervalInput.addEventListener("change", function () {
      let value = parseFloat(this.value);
      if (isNaN(value) || value < 0) {
        this.value = 0;
      }
    });
  }

  // Toggle switch events
  const toggleSwitches = document.querySelectorAll(".toggle-switch");
  toggleSwitches.forEach((toggleSwitch) => {
    toggleSwitch.addEventListener("click", function (e) {
      e.stopPropagation();
      const checkbox = this.querySelector('input[type="checkbox"]');
      if (checkbox) {
        checkbox.checked = !checkbox.checked;
      }
    });
  });

  // Save button
  const saveBtn = document.getElementById("saveBtn");
  if (saveBtn) {
    saveBtn.addEventListener("click", saveConfig);
  }

  // Reset button
  const resetBtn = document.getElementById("resetBtn");
  if (resetBtn) {
    resetBtn.addEventListener("click", resetConfig); // resetConfig will open the modal
  }

  // Scroll buttons
  window.addEventListener("scroll", toggleScrollButtons);

  // API Key Modal Elements and Events
  const addApiKeyBtn = document.getElementById("addApiKeyBtn");
  const closeApiKeyModalBtn = document.getElementById("closeApiKeyModalBtn");
  const cancelAddApiKeyBtn = document.getElementById("cancelAddApiKeyBtn");
  const confirmAddApiKeyBtn = document.getElementById("confirmAddApiKeyBtn");

  if (addApiKeyBtn) {
    addApiKeyBtn.addEventListener("click", () => {
      openModal(apiKeyModal);
      if (apiKeyBulkInput) apiKeyBulkInput.value = "";
    });
  }
  if (closeApiKeyModalBtn)
    closeApiKeyModalBtn.addEventListener("click", () =>
      closeModal(apiKeyModal)
    );
  if (cancelAddApiKeyBtn)
    cancelAddApiKeyBtn.addEventListener("click", () => closeModal(apiKeyModal));
  if (confirmAddApiKeyBtn)
    confirmAddApiKeyBtn.addEventListener("click", handleBulkAddApiKeys);
  if (apiKeySearchInput)
    apiKeySearchInput.addEventListener("input", handleApiKeySearch);

  // API Key Pagination Event Listeners
  const apiKeyPrevBtn = document.getElementById("apiKeyPrevBtn");
  const apiKeyNextBtn = document.getElementById("apiKeyNextBtn");
  
  if (apiKeyPrevBtn) {
    apiKeyPrevBtn.addEventListener("click", prevApiKeyPage);
  }
  if (apiKeyNextBtn) {
    apiKeyNextBtn.addEventListener("click", nextApiKeyPage);
  }

  // Bulk Delete API Key Modal Elements and Events
  const bulkDeleteApiKeyBtn = document.getElementById("bulkDeleteApiKeyBtn");
  const closeBulkDeleteModalBtn = document.getElementById(
    "closeBulkDeleteModalBtn"
  );
  const cancelBulkDeleteApiKeyBtn = document.getElementById(
    "cancelBulkDeleteApiKeyBtn"
  );
  const confirmBulkDeleteApiKeyBtn = document.getElementById(
    "confirmBulkDeleteApiKeyBtn"
  );

  if (bulkDeleteApiKeyBtn) {
    bulkDeleteApiKeyBtn.addEventListener("click", () => {
      openModal(bulkDeleteApiKeyModal);
      if (bulkDeleteApiKeyInput) bulkDeleteApiKeyInput.value = "";
    });
  }
  if (closeBulkDeleteModalBtn)
    closeBulkDeleteModalBtn.addEventListener("click", () =>
      closeModal(bulkDeleteApiKeyModal)
    );
  if (cancelBulkDeleteApiKeyBtn)
    cancelBulkDeleteApiKeyBtn.addEventListener("click", () =>
      closeModal(bulkDeleteApiKeyModal)
    );
  if (confirmBulkDeleteApiKeyBtn)
    confirmBulkDeleteApiKeyBtn.addEventListener(
      "click",
      handleBulkDeleteApiKeys
    );

  // Reset Confirmation Modal Elements and Events
  const closeResetModalBtn = document.getElementById("closeResetModalBtn");
  const cancelResetBtn = document.getElementById("cancelResetBtn");
  const confirmResetBtn = document.getElementById("confirmResetBtn");

  if (closeResetModalBtn)
    closeResetModalBtn.addEventListener("click", () =>
      closeModal(resetConfirmModal)
    );
  if (cancelResetBtn)
    cancelResetBtn.addEventListener("click", () =>
      closeModal(resetConfirmModal)
    );
  if (confirmResetBtn) {
    confirmResetBtn.addEventListener("click", () => {
      closeModal(resetConfirmModal);
      executeReset();
    });
  }

  // Click outside modal to close
  window.addEventListener("click", (event) => {
    const modals = [
      apiKeyModal,
      resetConfirmModal,
      bulkDeleteApiKeyModal,
      vertexApiKeyModal,
      bulkDeleteVertexApiKeyModal,
      modelHelperModal,
    ];
    modals.forEach((modal) => {
      if (event.target === modal) {
        closeModal(modal);
      }
    });
  });

  // Removed static token generation button event listener, now handled dynamically if needed or by specific buttons.

  // Authentication token generation button
  const generateAuthTokenBtn = document.getElementById("generateAuthTokenBtn");
  const authTokenInput = document.getElementById("AUTH_TOKEN");
  if (generateAuthTokenBtn && authTokenInput) {
    generateAuthTokenBtn.addEventListener("click", function () {
      const newToken = generateRandomToken(); // Assuming generateRandomToken is defined elsewhere
      authTokenInput.value = newToken;
      if (authTokenInput.classList.contains(SENSITIVE_INPUT_CLASS)) {
        const event = new Event("focusout", {
          bubbles: true,
          cancelable: true,
        });
        authTokenInput.dispatchEvent(event);
      }
      showNotification("已生成新认证令牌", "success");
    });
  }

  // Event delegation for dynamically added remove buttons and generate token buttons within array items
  if (configForm) {
    // Ensure configForm exists before adding event listener
    configForm.addEventListener("click", function (event) {
      const target = event.target;
      const removeButton = target.closest(".remove-btn");
      const generateButton = target.closest(".generate-btn");

      if (removeButton && removeButton.closest(`.${ARRAY_ITEM_CLASS}`)) {
        const arrayItem = removeButton.closest(`.${ARRAY_ITEM_CLASS}`);
        arrayItem.remove();
      } else if (
        generateButton &&
        generateButton.closest(`.${ARRAY_ITEM_CLASS}`)
      ) {
        const inputField = generateButton
          .closest(`.${ARRAY_ITEM_CLASS}`)
          .querySelector(`.${ARRAY_INPUT_CLASS}`);
        if (inputField) {
          const newToken = generateRandomToken();
          inputField.value = newToken;
          if (inputField.classList.contains(SENSITIVE_INPUT_CLASS)) {
            const event = new Event("focusout", {
              bubbles: true,
              cancelable: true,
            });
            inputField.dispatchEvent(event);
          }
          showNotification("已生成新令牌", "success");
        }
      }
    });
  }

  // Add Custom Header button
  const addCustomHeaderBtn = document.getElementById("addCustomHeaderBtn");
  if (addCustomHeaderBtn) {
    addCustomHeaderBtn.addEventListener("click", () => addCustomHeaderItem());
  }

  initializeSensitiveFields(); // Initialize sensitive field handling

  // Vertex Express API Key Modal Elements and Events
  const addVertexApiKeyBtn = document.getElementById("addVertexApiKeyBtn");
  const closeVertexApiKeyModalBtn = document.getElementById(
    "closeVertexApiKeyModalBtn"
  );
  const cancelAddVertexApiKeyBtn = document.getElementById(
    "cancelAddVertexApiKeyBtn"
  );
  const confirmAddVertexApiKeyBtn = document.getElementById(
    "confirmAddVertexApiKeyBtn"
  );
  const bulkDeleteVertexApiKeyBtn = document.getElementById(
    "bulkDeleteVertexApiKeyBtn"
  );
  const closeBulkDeleteVertexModalBtn = document.getElementById(
    "closeBulkDeleteVertexModalBtn"
  );
  const cancelBulkDeleteVertexApiKeyBtn = document.getElementById(
    "cancelBulkDeleteVertexApiKeyBtn"
  );
  const confirmBulkDeleteVertexApiKeyBtn = document.getElementById(
    "confirmBulkDeleteVertexApiKeyBtn"
  );

  if (addVertexApiKeyBtn) {
    addVertexApiKeyBtn.addEventListener("click", () => {
      openModal(vertexApiKeyModal);
      if (vertexApiKeyBulkInput) vertexApiKeyBulkInput.value = "";
    });
  }
  if (closeVertexApiKeyModalBtn)
    closeVertexApiKeyModalBtn.addEventListener("click", () =>
      closeModal(vertexApiKeyModal)
    );
  if (cancelAddVertexApiKeyBtn)
    cancelAddVertexApiKeyBtn.addEventListener("click", () =>
      closeModal(vertexApiKeyModal)
    );
  if (confirmAddVertexApiKeyBtn)
    confirmAddVertexApiKeyBtn.addEventListener(
      "click",
      handleBulkAddVertexApiKeys
    );

  if (bulkDeleteVertexApiKeyBtn) {
    bulkDeleteVertexApiKeyBtn.addEventListener("click", () => {
      openModal(bulkDeleteVertexApiKeyModal);
      if (bulkDeleteVertexApiKeyInput) bulkDeleteVertexApiKeyInput.value = "";
    });
  }
  if (closeBulkDeleteVertexModalBtn)
    closeBulkDeleteVertexModalBtn.addEventListener("click", () =>
      closeModal(bulkDeleteVertexApiKeyModal)
    );
  if (cancelBulkDeleteVertexApiKeyBtn)
    cancelBulkDeleteVertexApiKeyBtn.addEventListener("click", () =>
      closeModal(bulkDeleteVertexApiKeyModal)
    );
  if (confirmBulkDeleteVertexApiKeyBtn)
    confirmBulkDeleteVertexApiKeyBtn.addEventListener(
      "click",
      handleBulkDeleteVertexApiKeys
    );

  // Model Helper Modal Event Listeners
  if (closeModelHelperModalBtn) {
    closeModelHelperModalBtn.addEventListener("click", () =>
      closeModal(modelHelperModal)
    );
  }
  if (cancelModelHelperBtn) {
    cancelModelHelperBtn.addEventListener("click", () =>
      closeModal(modelHelperModal)
    );
  }
  if (modelHelperSearchInput) {
    modelHelperSearchInput.addEventListener("input", () =>
      renderModelsInModal()
    );
  }

  // Add event listeners to all model helper trigger buttons
  const modelHelperTriggerBtns = document.querySelectorAll(
    ".model-helper-trigger-btn"
  );
  modelHelperTriggerBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetInputId = btn.dataset.targetInputId;
      const targetArrayKey = btn.dataset.targetArrayKey;

      if (targetInputId) {
        currentModelHelperTarget = {
          type: "input",
          target: document.getElementById(targetInputId),
        };
      } else if (targetArrayKey) {
        currentModelHelperTarget = { type: "array", targetKey: targetArrayKey };
      }
      openModelHelperModal();
    });
  });
}); // <-- DOMContentLoaded end

/**
 * Initializes sensitive input field behavior (masking/unmasking).
 */
function initializeSensitiveFields() {
  if (!configForm) return;

  // Helper function: Mask field
  function maskField(field) {
    if (field.value && field.value !== MASKED_VALUE) {
      field.setAttribute("data-real-value", field.value);
      field.value = MASKED_VALUE;
    } else if (!field.value) {
      // If field value is empty string
      field.removeAttribute("data-real-value");
      // Ensure empty value doesn't show as asterisks
      if (field.value === MASKED_VALUE) field.value = "";
    }
  }

  // Helper function: Unmask field
  function unmaskField(field) {
    if (field.hasAttribute("data-real-value")) {
      field.value = field.getAttribute("data-real-value");
    }
    // If no data-real-value and value is MASKED_VALUE, it might be an initial empty sensitive field, clear it
    else if (
      field.value === MASKED_VALUE &&
      !field.hasAttribute("data-real-value")
    ) {
      field.value = "";
    }
  }

  // Initial masking for existing sensitive fields on page load
  // This function is called after populateForm and after dynamic element additions (via event delegation)
  function initialMaskAllExisting() {
    const sensitiveFields = configForm.querySelectorAll(
      `.${SENSITIVE_INPUT_CLASS}`
    );
    sensitiveFields.forEach((field) => {
      if (field.type === "password") {
        // For password fields, browser handles it. We just ensure data-original-type is set
        // and if it has a value, we also store data-real-value so it can be shown when switched to text
        if (field.value) {
          field.setAttribute("data-real-value", field.value);
        }
        // No need to set to MASKED_VALUE as browser handles it.
      } else if (
        field.type === "text" ||
        field.tagName.toLowerCase() === "textarea"
      ) {
        maskField(field);
      }
    });
  }
  initialMaskAllExisting();

  // Event delegation for dynamic and static fields
  configForm.addEventListener("focusin", function (event) {
    const target = event.target;
    if (target.classList.contains(SENSITIVE_INPUT_CLASS)) {
      if (target.type === "password") {
        // Record original type to switch back on blur
        if (!target.hasAttribute("data-original-type")) {
          target.setAttribute("data-original-type", "password");
        }
        target.type = "text"; // Switch to text type to show content
        // If data-real-value exists (e.g., set during populateForm), use it
        if (target.hasAttribute("data-real-value")) {
          target.value = target.getAttribute("data-real-value");
        }
        // Otherwise, the browser's existing password value will be shown directly
      } else {
        // For type="text" or textarea
        unmaskField(target);
      }
    }
  });

  configForm.addEventListener("focusout", function (event) {
    const target = event.target;
    if (target.classList.contains(SENSITIVE_INPUT_CLASS)) {
      // First, if the field is currently text and has a value, update data-real-value
      if (
        target.type === "text" ||
        target.tagName.toLowerCase() === "textarea"
      ) {
        if (target.value && target.value !== MASKED_VALUE) {
          target.setAttribute("data-real-value", target.value);
        } else if (!target.value) {
          // If value is empty, remove data-real-value
          target.removeAttribute("data-real-value");
        }
      }

      // Then handle type switching and masking
      if (
        target.getAttribute("data-original-type") === "password" &&
        target.type === "text"
      ) {
        target.type = "password"; // Switch back to password type
        // For password type, browser handles masking automatically, no need to set MASKED_VALUE manually
        // data-real-value has already been updated by the logic above
      } else if (
        target.type === "text" ||
        target.tagName.toLowerCase() === "textarea"
      ) {
        // For text or textarea sensitive fields, perform masking
        maskField(target);
      }
    }
  });
}

/**
 * Generates a UUID.
 * @returns {string} A new UUID.
 */
function generateUUID() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
    var r = (Math.random() * 16) | 0,
      v = c == "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/**
 * Initializes the configuration by fetching it from the server and populating the form.
 */
async function initConfig() {
  try {
    showNotification("正在加载配置...", "info");
    const response = await fetch("/api/config");

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const config = await response.json();

    // 确保数组字段有默认值
    if (
      !config.API_KEYS ||
      !Array.isArray(config.API_KEYS) ||
      config.API_KEYS.length === 0
    ) {
      config.API_KEYS = ["请在此处输入 API 密钥"];
    }

    if (
      !config.ALLOWED_TOKENS ||
      !Array.isArray(config.ALLOWED_TOKENS) ||
      config.ALLOWED_TOKENS.length === 0
    ) {
      config.ALLOWED_TOKENS = [""];
    }

    // --- 新增：处理 VERTEX_API_KEYS 默认值 ---
    if (!config.VERTEX_API_KEYS || !Array.isArray(config.VERTEX_API_KEYS)) {
      config.VERTEX_API_KEYS = [];
    }
    // --- 新增：处理 VERTEX_EXPRESS_BASE_URL 默认值 ---
    if (typeof config.VERTEX_EXPRESS_BASE_URL === "undefined") {
      config.VERTEX_EXPRESS_BASE_URL = "";
    }
    // --- 新增：处理 CUSTOM_HEADERS 默认值 ---
    if (
      !config.CUSTOM_HEADERS ||
      typeof config.CUSTOM_HEADERS !== "object" ||
      config.CUSTOM_HEADERS === null
    ) {
      config.CUSTOM_HEADERS = {}; // 默认为空对象
    }
    // --- 新增：处理自动删除错误日志配置的默认值 ---
    if (typeof config.AUTO_DELETE_ERROR_LOGS_ENABLED === "undefined") {
      config.AUTO_DELETE_ERROR_LOGS_ENABLED = false;
    }
    if (typeof config.AUTO_DELETE_ERROR_LOGS_DAYS === "undefined") {
      config.AUTO_DELETE_ERROR_LOGS_DAYS = 7;
    }
    // 错误日志是否记录请求体（默认不记录）
    if (typeof config.ERROR_LOG_RECORD_REQUEST_BODY === "undefined") {
      config.ERROR_LOG_RECORD_REQUEST_BODY = false;
    }
    // --- 结束：处理自动删除错误日志配置的默认值 ---

    // --- 新增：处理自动删除请求日志配置的默认值 ---
    if (typeof config.AUTO_DELETE_REQUEST_LOGS_ENABLED === "undefined") {
      config.AUTO_DELETE_REQUEST_LOGS_ENABLED = false;
    }
    if (typeof config.AUTO_DELETE_REQUEST_LOGS_DAYS === "undefined") {
      config.AUTO_DELETE_REQUEST_LOGS_DAYS = 30;
    }
    // --- 结束：处理自动删除请求日志配置的默认值 ---

    populateForm(config);
    // After populateForm, initialize masking for all populated sensitive fields
    if (configForm) {
      // Ensure form exists
      initializeSensitiveFields(); // Call initializeSensitiveFields to handle initial masking
    }

    showNotification("配置加载成功", "success");
  } catch (error) {
    console.error("加载配置失败:", error);
    showNotification("加载配置失败: " + error.message, "error");

    // 加载失败时，使用默认配置
    const defaultConfig = {
      API_KEYS: [""],
      ALLOWED_TOKENS: [""],
      VERTEX_API_KEYS: [], // 确保默认值存在
      VERTEX_EXPRESS_BASE_URL: "", // 确保默认值存在
      CUSTOM_HEADERS: {},
      AUTO_DELETE_ERROR_LOGS_ENABLED: false,
      AUTO_DELETE_ERROR_LOGS_DAYS: 7, // 新增默认值
      AUTO_DELETE_REQUEST_LOGS_ENABLED: false, // 新增默认值
      AUTO_DELETE_REQUEST_LOGS_DAYS: 30, // 新增默认值
    };

    populateForm(defaultConfig);
    if (configForm) {
      // Ensure form exists
      initializeSensitiveFields(); // Call initializeSensitiveFields to handle initial masking
    }
  }
}

/**
 * Populates the configuration form with data.
 * @param {object} config - The configuration object.
 */
function populateForm(config) {
  // 1. Clear existing dynamic content first
  const arrayContainers = document.querySelectorAll(".array-container");
  arrayContainers.forEach((container) => {
    container.innerHTML = ""; // Clear all array containers
  });
  // Populate CUSTOM_HEADERS
  const customHeadersContainer = document.getElementById(
    "CUSTOM_HEADERS_container"
  );
  let customHeadersAdded = false;
  if (
    customHeadersContainer &&
    config.CUSTOM_HEADERS &&
    typeof config.CUSTOM_HEADERS === "object"
  ) {
    for (const [key, value] of Object.entries(config.CUSTOM_HEADERS)) {
      createAndAppendCustomHeaderItem(key, value);
      customHeadersAdded = true;
    }
  }
  if (!customHeadersAdded && customHeadersContainer) {
    customHeadersContainer.innerHTML =
      '<div class="text-gray-500 text-sm italic">添加自定义请求头，例如 X-Api-Key: your-key</div>';
  }

  // 4. Populate other array fields (excluding API_KEYS which uses pagination)
  for (const [key, value] of Object.entries(config)) {
    if (Array.isArray(value) && key !== "API_KEYS") {
      const container = document.getElementById(`${key}_container`);
      if (container) {
        value.forEach((itemValue) => {
          if (typeof itemValue === "string") {
            addArrayItemWithValue(key, itemValue);
          } else {
            console.warn(`Invalid item found in array '${key}':`, itemValue);
          }
        });
      }
    }
  }

  // 4.1. 特殊处理API_KEYS - 使用分页
  if (Array.isArray(config.API_KEYS)) {
    allApiKeys = config.API_KEYS.filter(key =>
      typeof key === "string" && key.trim() !== ""
    );
    filteredApiKeys = [...allApiKeys];
    currentApiKeyPage = 1;
    renderApiKeyPage();
    updateApiKeyPagination();
  }

  // 5. Populate non-array/non-budget fields
  for (const [key, value] of Object.entries(config)) {
    if (
      !Array.isArray(value) &&
      !(
        typeof value === "object" &&
        value !== null &&
        key === "THINKING_BUDGET_MAP"
      )
    ) {
      const element = document.getElementById(key);
      if (element) {
        if (element.type === "checkbox" && typeof value === "boolean") {
          element.checked = value;
        } else if (element.type !== "checkbox") {
          if (key === "LOG_LEVEL" && typeof value === "string") {
            element.value = value.toUpperCase();
          } else {
            element.value = value !== null && value !== undefined ? value : "";
          }
        }
      }
    }
  }

  // --- 新增：处理自动删除错误日志的字段 ---
  const autoDeleteEnabledCheckbox = document.getElementById(
    "AUTO_DELETE_ERROR_LOGS_ENABLED"
  );
  const autoDeleteDaysSelect = document.getElementById(
    "AUTO_DELETE_ERROR_LOGS_DAYS"
  );

  if (autoDeleteEnabledCheckbox && autoDeleteDaysSelect) {
    autoDeleteEnabledCheckbox.checked = !!config.AUTO_DELETE_ERROR_LOGS_ENABLED; // 确保是布尔值
    autoDeleteDaysSelect.value = config.AUTO_DELETE_ERROR_LOGS_DAYS || 7; // 默认7天

    // 根据复选框状态设置下拉框的禁用状态
    autoDeleteDaysSelect.disabled = !autoDeleteEnabledCheckbox.checked;

    // 添加事件监听器
    autoDeleteEnabledCheckbox.addEventListener("change", function () {
      autoDeleteDaysSelect.disabled = !this.checked;
    });
  }
  // --- 结束：处理自动删除错误日志的字段 ---

  // --- 新增：处理自动删除请求日志的字段 ---
  const autoDeleteRequestEnabledCheckbox = document.getElementById(
    "AUTO_DELETE_REQUEST_LOGS_ENABLED"
  );
  const autoDeleteRequestDaysSelect = document.getElementById(
    "AUTO_DELETE_REQUEST_LOGS_DAYS"
  );

  if (autoDeleteRequestEnabledCheckbox && autoDeleteRequestDaysSelect) {
    autoDeleteRequestEnabledCheckbox.checked =
      !!config.AUTO_DELETE_REQUEST_LOGS_ENABLED;
    autoDeleteRequestDaysSelect.value =
      config.AUTO_DELETE_REQUEST_LOGS_DAYS || 30;
    autoDeleteRequestDaysSelect.disabled =
      !autoDeleteRequestEnabledCheckbox.checked;

    autoDeleteRequestEnabledCheckbox.addEventListener("change", function () {
      autoDeleteRequestDaysSelect.disabled = !this.checked;
    });
  }
  // --- 结束：处理自动删除请求日志的字段 ---
}

/**
 * Handles the bulk addition of API keys from the modal input.
 */
function handleBulkAddApiKeys() {
  if (!apiKeyBulkInput || !apiKeyModal) return;

  const bulkText = apiKeyBulkInput.value;
  const extractedKeys = bulkText.match(API_KEY_REGEX) || [];

  // 合并现有密钥和新密钥，去重
  const combinedKeys = new Set([...allApiKeys, ...extractedKeys]);
  const uniqueKeys = Array.from(combinedKeys);

  // 更新全局密钥数组
  allApiKeys = uniqueKeys;
  
  // 更新过滤后的数组
  const searchTerm = apiKeySearchInput ? apiKeySearchInput.value.toLowerCase() : "";
  if (!searchTerm) {
    filteredApiKeys = [...allApiKeys];
  } else {
    filteredApiKeys = allApiKeys.filter(key =>
      key.toLowerCase().includes(searchTerm)
    );
  }

  // 重新渲染当前页
  renderApiKeyPage();
  updateApiKeyPagination();

  closeModal(apiKeyModal);
  showNotification(`添加/更新了 ${uniqueKeys.length} 个唯一密钥`, "success");
}

/**
 * Handles searching/filtering of API keys in the list.
 */
function handleApiKeySearch() {
  if (!apiKeySearchInput) return;

  const searchTerm = apiKeySearchInput.value.toLowerCase();
  
  // 过滤API密钥
  if (!searchTerm) {
    filteredApiKeys = [...allApiKeys];
  } else {
    filteredApiKeys = allApiKeys.filter(key =>
      key.toLowerCase().includes(searchTerm)
    );
  }

  // 重置到第一页
  currentApiKeyPage = 1;
  
  // 重新渲染当前页
  renderApiKeyPage();
  updateApiKeyPagination();
}

/**
 * 渲染当前页的API密钥
 */
function renderApiKeyPage() {
  const apiKeyContainer = document.getElementById("API_KEYS_container");
  if (!apiKeyContainer) return;

  // 清空容器
  apiKeyContainer.innerHTML = "";

  // 计算当前页的数据范围
  const startIndex = (currentApiKeyPage - 1) * API_KEYS_PER_PAGE;
  const endIndex = Math.min(startIndex + API_KEYS_PER_PAGE, filteredApiKeys.length);
  const pageKeys = filteredApiKeys.slice(startIndex, endIndex);

  // 渲染当前页的密钥
  pageKeys.forEach((key) => {
    addArrayItemWithValue("API_KEYS", key);
  });

  // 如果没有密钥，显示提示信息
  if (pageKeys.length === 0) {
    const emptyMessage = document.createElement("div");
    emptyMessage.className = "text-gray-500 text-sm italic text-center py-4";
    emptyMessage.textContent = filteredApiKeys.length === 0 ?
      (allApiKeys.length === 0 ? "暂无API密钥" : "未找到匹配的密钥") :
      "当前页无数据";
    apiKeyContainer.appendChild(emptyMessage);
  }
}

/**
 * 更新分页控件
 */
function updateApiKeyPagination() {
  totalApiKeyPages = Math.max(1, Math.ceil(filteredApiKeys.length / API_KEYS_PER_PAGE));
  
  // 确保当前页在有效范围内
  if (currentApiKeyPage > totalApiKeyPages) {
    currentApiKeyPage = totalApiKeyPages;
  }

  const paginationContainer = document.getElementById("apiKeyPagination");
  if (!paginationContainer) return;

  // 如果只有一页或没有数据，隐藏分页控件
  if (totalApiKeyPages <= 1) {
    paginationContainer.style.display = "none";
    return;
  }

  paginationContainer.style.display = "flex";

  // 更新页码信息
  const pageInfo = document.getElementById("apiKeyPageInfo");
  if (pageInfo) {
    pageInfo.textContent = `第 ${currentApiKeyPage} 页，共 ${totalApiKeyPages} 页 (${filteredApiKeys.length} 个密钥)`;
  }

  // 更新按钮状态
  const prevBtn = document.getElementById("apiKeyPrevBtn");
  const nextBtn = document.getElementById("apiKeyNextBtn");
  
  if (prevBtn) {
    prevBtn.disabled = currentApiKeyPage <= 1;
    prevBtn.className = currentApiKeyPage <= 1 ?
      "px-3 py-1 rounded bg-gray-300 text-gray-500 cursor-not-allowed" :
      "px-3 py-1 rounded bg-blue-500 text-white hover:bg-blue-600 cursor-pointer";
  }
  
  if (nextBtn) {
    nextBtn.disabled = currentApiKeyPage >= totalApiKeyPages;
    nextBtn.className = currentApiKeyPage >= totalApiKeyPages ?
      "px-3 py-1 rounded bg-gray-300 text-gray-500 cursor-not-allowed" :
      "px-3 py-1 rounded bg-blue-500 text-white hover:bg-blue-600 cursor-pointer";
  }
}

/**
 * 跳转到指定页
 */
function goToApiKeyPage(page) {
  if (page < 1 || page > totalApiKeyPages) return;
  
  currentApiKeyPage = page;
  renderApiKeyPage();
  updateApiKeyPagination();
}

/**
 * 上一页
 */
function prevApiKeyPage() {
  if (currentApiKeyPage > 1) {
    goToApiKeyPage(currentApiKeyPage - 1);
  }
}

/**
 * 下一页
 */
function nextApiKeyPage() {
  if (currentApiKeyPage < totalApiKeyPages) {
    goToApiKeyPage(currentApiKeyPage + 1);
  }
}

/**
 * Handles the bulk deletion of API keys based on input from the modal.
 */
function handleBulkDeleteApiKeys() {
  if (!bulkDeleteApiKeyInput || !bulkDeleteApiKeyModal) return;

  const bulkText = bulkDeleteApiKeyInput.value;
  if (!bulkText.trim()) {
    showNotification("请粘贴需要删除的 API 密钥", "warning");
    return;
  }

  const keysToDelete = new Set(bulkText.match(API_KEY_REGEX) || []);

  if (keysToDelete.size === 0) {
    showNotification("未在输入内容中提取到有效的 API 密钥格式", "warning");
    return;
  }

  // 从allApiKeys数组中删除匹配的密钥
  let deleteCount = 0;
  allApiKeys = allApiKeys.filter(key => {
    if (keysToDelete.has(key)) {
      deleteCount++;
      return false;
    }
    return true;
  });

  // 更新过滤后的数组
  const searchTerm = apiKeySearchInput ? apiKeySearchInput.value.toLowerCase() : "";
  if (!searchTerm) {
    filteredApiKeys = [...allApiKeys];
  } else {
    filteredApiKeys = allApiKeys.filter(key =>
      key.toLowerCase().includes(searchTerm)
    );
  }

  // 重新渲染当前页
  renderApiKeyPage();
  updateApiKeyPagination();

  closeModal(bulkDeleteApiKeyModal);

  if (deleteCount > 0) {
    showNotification(`成功删除了 ${deleteCount} 个匹配的密钥`, "success");
  } else {
    showNotification("列表中未找到您输入的任何密钥进行删除", "info");
  }
  bulkDeleteApiKeyInput.value = "";
}

/**
 * Handles the bulk addition of Vertex Express API keys from the modal input.
 */
function handleBulkAddVertexApiKeys() {
  const vertexApiKeyContainer = document.getElementById(
    "VERTEX_API_KEYS_container"
  );
  if (!vertexApiKeyBulkInput || !vertexApiKeyContainer || !vertexApiKeyModal) {
    return;
  }

  const bulkText = vertexApiKeyBulkInput.value;
  const extractedKeys = bulkText.match(VERTEX_API_KEY_REGEX) || [];

  const currentKeyInputs = vertexApiKeyContainer.querySelectorAll(
    `.${ARRAY_INPUT_CLASS}.${SENSITIVE_INPUT_CLASS}`
  );
  let currentKeys = Array.from(currentKeyInputs)
    .map((input) => {
      return input.hasAttribute("data-real-value")
        ? input.getAttribute("data-real-value")
        : input.value;
    })
    .filter((key) => key && key.trim() !== "" && key !== MASKED_VALUE);

  const combinedKeys = new Set([...currentKeys, ...extractedKeys]);
  const uniqueKeys = Array.from(combinedKeys);

  vertexApiKeyContainer.innerHTML = ""; // Clear existing items

  uniqueKeys.forEach((key) => {
    addArrayItemWithValue("VERTEX_API_KEYS", key); // VERTEX_API_KEYS are sensitive
  });

  // Ensure new sensitive inputs are masked
  const newKeyInputs = vertexApiKeyContainer.querySelectorAll(
    `.${ARRAY_INPUT_CLASS}.${SENSITIVE_INPUT_CLASS}`
  );
  newKeyInputs.forEach((input) => {
    if (configForm && typeof initializeSensitiveFields === "function") {
      const focusoutEvent = new Event("focusout", {
        bubbles: true,
        cancelable: true,
      });
      input.dispatchEvent(focusoutEvent);
    }
  });

  closeModal(vertexApiKeyModal);
  showNotification(
    `添加/更新了 ${uniqueKeys.length} 个唯一 Vertex 密钥`,
    "success"
  );
  vertexApiKeyBulkInput.value = "";
}

/**
 * Handles the bulk deletion of Vertex Express API keys based on input from the modal.
 */
function handleBulkDeleteVertexApiKeys() {
  const vertexApiKeyContainer = document.getElementById(
    "VERTEX_API_KEYS_container"
  );
  if (
    !bulkDeleteVertexApiKeyInput ||
    !vertexApiKeyContainer ||
    !bulkDeleteVertexApiKeyModal
  ) {
    return;
  }

  const bulkText = bulkDeleteVertexApiKeyInput.value;
  if (!bulkText.trim()) {
    showNotification("请粘贴需要删除的 Vertex Express API 密钥", "warning");
    return;
  }

  const keysToDelete = new Set(bulkText.match(VERTEX_API_KEY_REGEX) || []);

  if (keysToDelete.size === 0) {
    showNotification(
      "未在输入内容中提取到有效的 Vertex Express API 密钥格式",
      "warning"
    );
    return;
  }

  const keyItems = vertexApiKeyContainer.querySelectorAll(
    `.${ARRAY_ITEM_CLASS}`
  );
  let deleteCount = 0;

  keyItems.forEach((item) => {
    const input = item.querySelector(
      `.${ARRAY_INPUT_CLASS}.${SENSITIVE_INPUT_CLASS}`
    );
    const realValue =
      input &&
      (input.hasAttribute("data-real-value")
        ? input.getAttribute("data-real-value")
        : input.value);
    if (realValue && keysToDelete.has(realValue)) {
      item.remove();
      deleteCount++;
    }
  });

  closeModal(bulkDeleteVertexApiKeyModal);

  if (deleteCount > 0) {
    showNotification(
      `成功删除了 ${deleteCount} 个匹配的 Vertex 密钥`,
      "success"
    );
  } else {
    showNotification("列表中未找到您输入的任何 Vertex 密钥进行删除", "info");
  }
  bulkDeleteVertexApiKeyInput.value = "";
}

/**
 * Switches the active configuration tab.
 * @param {string} tabId - The ID of the tab to switch to.
 */
function switchTab(tabId) {
  console.log(`Switching to tab: ${tabId}`);

  // 定义选中态和未选中态的样式
  const activeStyle =
    "background-color: #3b82f6 !important; color: #ffffff !important; border: 2px solid #2563eb !important; box-shadow: 0 4px 12px -2px rgba(59, 130, 246, 0.4), 0 2px 6px -1px rgba(59, 130, 246, 0.2) !important; transform: translateY(-2px) !important; font-weight: 600 !important;";
  const inactiveStyle =
    "background-color: #f8fafc !important; color: #64748b !important; border: 2px solid #e2e8f0 !important; box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1) !important; font-weight: 500 !important; transform: none !important;";

  // 更新标签按钮状态
  const tabButtons = document.querySelectorAll(".tab-btn");
  console.log(`Found ${tabButtons.length} tab buttons`);

  tabButtons.forEach((button) => {
    const buttonTabId = button.getAttribute("data-tab");
    if (buttonTabId === tabId) {
      // 激活状态：直接设置内联样式
      button.classList.add("active");
      button.setAttribute("style", activeStyle);
      console.log(`Applied active style to button: ${buttonTabId}`);
    } else {
      // 非激活状态：直接设置内联样式
      button.classList.remove("active");
      button.setAttribute("style", inactiveStyle);
      console.log(`Applied inactive style to button: ${buttonTabId}`);
    }
  });

  // 更新内容区域
  const sections = document.querySelectorAll(".config-section");
  sections.forEach((section) => {
    if (section.id === `${tabId}-section`) {
      section.classList.add("active");
    } else {
      section.classList.remove("active");
    }
  });
}

/**
 * Creates and appends an input field for an array item.
 * @param {string} key - The configuration key for the array.
 * @param {string} value - The initial value for the input field.
 * @param {boolean} isSensitive - Whether the input is for sensitive data.
 * @returns {HTMLInputElement} The created input element.
 */
function createArrayInput(key, value, isSensitive) {
  const input = document.createElement("input");
  input.type = "text";
  input.name = `${key}[]`;
  input.value = value;
  let inputClasses = `${ARRAY_INPUT_CLASS} flex-grow px-3 py-2 border-none rounded-l-md focus:outline-none form-input-themed`;
  if (isSensitive) {
    inputClasses += ` ${SENSITIVE_INPUT_CLASS}`;
  }
  input.className = inputClasses;
  return input;
}

/**
 * Creates a generate token button for allowed tokens.
 * @returns {HTMLButtonElement} The created button element.
 */
function createGenerateTokenButton() {
  const generateBtn = document.createElement("button");
  generateBtn.type = "button";
  generateBtn.className =
    "generate-btn px-2 py-2 text-gray-500 hover:text-primary-600 focus:outline-none rounded-r-md bg-gray-100 hover:bg-gray-200 transition-colors";
  generateBtn.innerHTML = '<i class="fas fa-dice"></i>';
  generateBtn.title = "生成随机令牌";
  // Event listener will be added via delegation in DOMContentLoaded
  return generateBtn;
}

/**
 * Creates a remove button for an array item.
 * @returns {HTMLButtonElement} The created button element.
 */
function createRemoveButton() {
  const removeBtn = document.createElement("button");
  removeBtn.type = "button";
  removeBtn.className =
    "remove-btn text-gray-400 hover:text-red-500 focus:outline-none transition-colors duration-150";
  removeBtn.innerHTML = '<i class="fas fa-trash-alt"></i>';
  removeBtn.title = "删除";
  // Event listener will be added via delegation in DOMContentLoaded
  return removeBtn;
}

/**
 * Adds a new item to an array configuration section (e.g., API_KEYS, ALLOWED_TOKENS).
 * This function is typically called by a "+" button.
 * @param {string} key - The configuration key for the array (e.g., 'API_KEYS').
 */
function addArrayItem(key) {
  const container = document.getElementById(`${key}_container`);
  if (!container) return;

  const newItemValue = ""; // New items start empty
  addArrayItemWithValue(key, newItemValue);
}

/**
 * Adds an array item with a specific value to the DOM.
 * This is used both for initially populating the form and for adding new items.
 * @param {string} key - The configuration key (e.g., 'API_KEYS').
 * @param {string} value - The value for the array item.
 */
function addArrayItemWithValue(key, value) {
  const container = document.getElementById(`${key}_container`);
  if (!container) return;

  const isAllowedToken = key === "ALLOWED_TOKENS";
  const isVertexApiKey = key === "VERTEX_API_KEYS";
  const isSensitive = key === "API_KEYS" || isAllowedToken || isVertexApiKey;

  const arrayItem = document.createElement("div");
  arrayItem.className = `${ARRAY_ITEM_CLASS} flex items-center mb-2 gap-2`;

  const inputWrapper = document.createElement("div");
  inputWrapper.className =
    "flex items-center flex-grow rounded-md focus-within:border-blue-500 focus-within:ring focus-within:ring-blue-500 focus-within:ring-opacity-50";
  inputWrapper.style.border = "1px solid rgba(0, 0, 0, 0.12)";
  inputWrapper.style.backgroundColor = "transparent";

  const input = createArrayInput(key, value, isSensitive);
  inputWrapper.appendChild(input);

  if (isAllowedToken) {
    const generateBtn = createGenerateTokenButton();
    inputWrapper.appendChild(generateBtn);
  } else {
    input.classList.add("rounded-r-md");
  }

  const removeBtn = createRemoveButton();

  arrayItem.appendChild(inputWrapper);
  arrayItem.appendChild(removeBtn);
  container.appendChild(arrayItem);

  if (isSensitive && input.value) {
    if (configForm && typeof initializeSensitiveFields === "function") {
      const focusoutEvent = new Event("focusout", {
        bubbles: true,
        cancelable: true,
      });
      input.dispatchEvent(focusoutEvent);
    }
  }
}

/**
 * Adds a new custom header item to the DOM.
 */
function addCustomHeaderItem() {
  createAndAppendCustomHeaderItem("", "");
}

/**
 * Creates and appends a DOM element for a custom header.
 * @param {string} key - The header key.
 * @param {string} value - The header value.
 */
function createAndAppendCustomHeaderItem(key, value) {
  const container = document.getElementById("CUSTOM_HEADERS_container");
  if (!container) {
    console.error(
      "Cannot add custom header: CUSTOM_HEADERS_container not found!"
    );
    return;
  }

  const placeholder = container.querySelector(".text-gray-500.italic");
  if (
    placeholder &&
    container.children.length === 1 &&
    container.firstChild === placeholder
  ) {
    container.innerHTML = "";
  }

  const headerItem = document.createElement("div");
  headerItem.className = `${CUSTOM_HEADER_ITEM_CLASS} flex items-center mb-2 gap-2`;

  const keyInput = document.createElement("input");
  keyInput.type = "text";
  keyInput.value = key;
  keyInput.placeholder = "Header Name";
  keyInput.className = `${CUSTOM_HEADER_KEY_INPUT_CLASS} flex-grow px-3 py-2 border border-gray-300 rounded-md focus:outline-none bg-gray-100 text-gray-500`;

  const valueInput = document.createElement("input");
  valueInput.type = "text";
  valueInput.value = value;
  valueInput.placeholder = "Header Value";
  valueInput.className = `${CUSTOM_HEADER_VALUE_INPUT_CLASS} flex-grow px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:border-primary-500 focus:ring focus:ring-primary-200 focus:ring-opacity-50`;

  const removeBtn = createRemoveButton();
  removeBtn.addEventListener("click", () => {
    headerItem.remove();
    if (container.children.length === 0) {
      container.innerHTML =
        '<div class="text-gray-500 text-sm italic">添加自定义请求头，例如 X-Api-Key: your-key</div>';
    }
  });

  headerItem.appendChild(keyInput);
  headerItem.appendChild(valueInput);
  headerItem.appendChild(removeBtn);

  container.appendChild(headerItem);
}

/**
 * Collects all data from the configuration form.
 * @returns {object} An object containing all configuration data.
 */
function collectFormData() {
  const formData = {};

  // 处理普通输入和 select
  const inputsAndSelects = document.querySelectorAll(
    'input[type="text"], input[type="number"], input[type="password"], select, textarea'
  );
  inputsAndSelects.forEach((element) => {
    if (
      element.name &&
      !element.name.includes("[]") &&
      !element.closest(".array-container") &&
      !element.closest(`.${MAP_ITEM_CLASS}`)
    ) {
      if (element.type === "number") {
        formData[element.name] = parseFloat(element.value);
      } else if (
        element.classList.contains(SENSITIVE_INPUT_CLASS) &&
        element.hasAttribute("data-real-value")
      ) {
        formData[element.name] = element.getAttribute("data-real-value");
      } else {
        formData[element.name] = element.value;
      }
    }
  });

  const checkboxes = document.querySelectorAll('input[type="checkbox"]');
  checkboxes.forEach((checkbox) => {
    formData[checkbox.name] = checkbox.checked;
  });

  const arrayContainers = document.querySelectorAll(".array-container");
  arrayContainers.forEach((container) => {
    const key = container.id.replace("_container", "");
    
    // 特殊处理API_KEYS - 使用全局数组而不是DOM元素
    if (key === "API_KEYS") {
      formData[key] = allApiKeys.filter(
        (value) => value && value.trim() !== "" && value !== MASKED_VALUE
      );
      return;
    }
    
    const arrayInputs = container.querySelectorAll(`.${ARRAY_INPUT_CLASS}`);
    formData[key] = Array.from(arrayInputs)
      .map((input) => {
        if (
          input.classList.contains(SENSITIVE_INPUT_CLASS) &&
          input.hasAttribute("data-real-value")
        ) {
          return input.getAttribute("data-real-value");
        }
        return input.value;
      })
      .filter(
        (value) => value && value.trim() !== "" && value !== MASKED_VALUE
      ); // Ensure MASKED_VALUE is also filtered if not handled
  });

  const customHeadersContainer = document.getElementById(
    "CUSTOM_HEADERS_container"
  );
  if (customHeadersContainer) {
    formData["CUSTOM_HEADERS"] = {};
    const customHeaderItems = customHeadersContainer.querySelectorAll(
      `.${CUSTOM_HEADER_ITEM_CLASS}`
    );
    customHeaderItems.forEach((item) => {
      const keyInput = item.querySelector(`.${CUSTOM_HEADER_KEY_INPUT_CLASS}`);
      const valueInput = item.querySelector(
        `.${CUSTOM_HEADER_VALUE_INPUT_CLASS}`
      );
      if (keyInput && valueInput && keyInput.value.trim() !== "") {
        formData["CUSTOM_HEADERS"][keyInput.value.trim()] =
          valueInput.value.trim();
      }
    });
  }

  // --- 新增：收集自动删除错误日志的配置 ---
  const autoDeleteEnabledCheckbox = document.getElementById(
    "AUTO_DELETE_ERROR_LOGS_ENABLED"
  );
  if (autoDeleteEnabledCheckbox) {
    formData["AUTO_DELETE_ERROR_LOGS_ENABLED"] =
      autoDeleteEnabledCheckbox.checked;
  }

  const autoDeleteDaysSelect = document.getElementById(
    "AUTO_DELETE_ERROR_LOGS_DAYS"
  );
  if (autoDeleteDaysSelect) {
    // 如果复选框未选中，则不应提交天数，或者可以提交一个默认/无效值，
    // 但后端应该只在 ENABLED 为 true 时才关心 DAYS。
    // 这里我们总是收集它，后端逻辑会处理。
    formData["AUTO_DELETE_ERROR_LOGS_DAYS"] = parseInt(
      autoDeleteDaysSelect.value,
      10
    );
  }
  // --- 结束：收集自动删除错误日志的配置 ---

  // --- 新增：收集自动删除请求日志的配置 ---
  const autoDeleteRequestEnabledCheckbox = document.getElementById(
    "AUTO_DELETE_REQUEST_LOGS_ENABLED"
  );
  if (autoDeleteRequestEnabledCheckbox) {
    formData["AUTO_DELETE_REQUEST_LOGS_ENABLED"] =
      autoDeleteRequestEnabledCheckbox.checked;
  }

  const autoDeleteRequestDaysSelect = document.getElementById(
    "AUTO_DELETE_REQUEST_LOGS_DAYS"
  );
  if (autoDeleteRequestDaysSelect) {
    formData["AUTO_DELETE_REQUEST_LOGS_DAYS"] = parseInt(
      autoDeleteRequestDaysSelect.value,
      10
    );
  }
  // --- 结束：收集自动删除请求日志的配置 ---

  return formData;
}

/**
 * Stops the scheduler task on the server.
 */
async function stopScheduler() {
  try {
    const response = await fetch("/api/scheduler/stop", { method: "POST" });
    if (!response.ok) {
      console.warn(`停止定时任务失败: ${response.status}`);
    } else {
      console.log("定时任务已停止");
    }
  } catch (error) {
    console.error("调用停止定时任务API时出错:", error);
  }
}

/**
 * Starts the scheduler task on the server.
 */
async function startScheduler() {
  try {
    const response = await fetch("/api/scheduler/start", { method: "POST" });
    if (!response.ok) {
      console.warn(`启动定时任务失败: ${response.status}`);
    } else {
      console.log("定时任务已启动");
    }
  } catch (error) {
    console.error("调用启动定时任务API时出错:", error);
  }
}

/**
 * Saves the current configuration to the server.
 */
async function saveConfig() {
  try {
    const formData = collectFormData();

    showNotification("正在保存配置...", "info");

    // 1. 停止定时任务
    await stopScheduler();

    const response = await fetch("/api/config", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(formData),
    });

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(
        errorData.detail || `HTTP error! status: ${response.status}`
      );
    }

    const result = await response.json();

    // 移除居中的 saveStatus 提示

    showNotification("配置保存成功", "success");

    // 3. 启动新的定时任务
    await startScheduler();
  } catch (error) {
    console.error("保存配置失败:", error);
    // 保存失败时，也尝试重启定时任务，以防万一
    await startScheduler();
    // 移除居中的 saveStatus 提示

    showNotification("保存配置失败: " + error.message, "error");
  }
}

/**
 * Initiates the configuration reset process by showing a confirmation modal.
 * @param {Event} [event] - The click event, if triggered by a button.
 */
function resetConfig(event) {
  // 阻止事件冒泡和默认行为
  if (event) {
    event.preventDefault();
    event.stopPropagation();
  }

  console.log(
    "resetConfig called. Event target:",
    event ? event.target.id : "No event"
  );

  // Ensure modal is shown only if the event comes from the reset button
  if (
    !event ||
    event.target.id === "resetBtn" ||
    (event.currentTarget && event.currentTarget.id === "resetBtn")
  ) {
    if (resetConfirmModal) {
      openModal(resetConfirmModal);
    } else {
      console.error(
        "Reset confirmation modal not found! Falling back to default confirm."
      );
      if (confirm("确定要重置所有配置吗？这将恢复到默认值。")) {
        executeReset();
      }
    }
  }
}

/**
 * Executes the actual configuration reset after confirmation.
 */
async function executeReset() {
  try {
    showNotification("正在重置配置...", "info");

    // 1. 停止定时任务
    await stopScheduler();
    const response = await fetch("/api/config/reset", { method: "POST" });
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const config = await response.json();
    populateForm(config);
    // Re-initialize masking for sensitive fields after reset
    if (configForm && typeof initializeSensitiveFields === "function") {
      const sensitiveFields = configForm.querySelectorAll(
        `.${SENSITIVE_INPUT_CLASS}`
      );
      sensitiveFields.forEach((field) => {
        if (field.type === "password") {
          if (field.value) field.setAttribute("data-real-value", field.value);
        } else if (
          field.type === "text" ||
          field.tagName.toLowerCase() === "textarea"
        ) {
          const focusoutEvent = new Event("focusout", {
            bubbles: true,
            cancelable: true,
          });
          field.dispatchEvent(focusoutEvent);
        }
      });
    }
    showNotification("配置已重置为默认值", "success");

    // 3. 启动新的定时任务
    await startScheduler();
  } catch (error) {
    console.error("重置配置失败:", error);
    showNotification("重置配置失败: " + error.message, "error");
    // 重置失败时，也尝试重启定时任务
    await startScheduler();
  }
}

/**
 * Displays a notification message to the user.
 * @param {string} message - The message to display.
 * @param {string} [type='info'] - The type of notification ('info', 'success', 'error', 'warning').
 */
function showNotification(message, type = "info") {
  const notification = document.getElementById("notification");
  notification.textContent = message;

  // 统一样式为黑色半透明，与 keys_status.js 保持一致
  notification.classList.remove("bg-danger-500");
  notification.classList.add("bg-black");
  notification.style.backgroundColor = "rgba(0,0,0,0.8)";
  notification.style.color = "#fff";

  // 应用过渡效果
  notification.style.opacity = "1";
  notification.style.transform = "translate(-50%, 0)";

  // 设置自动消失
  setTimeout(() => {
    notification.style.opacity = "0";
    notification.style.transform = "translate(-50%, 10px)";
  }, 3000);
}

/**
 * Refreshes the current page.
 * @param {HTMLButtonElement} [button] - The button that triggered the refresh (to show loading state).
 */
function refreshPage(button) {
  if (button) button.classList.add("loading");
  location.reload();
}

/**
 * Scrolls the page to the top.
 */
function scrollToTop() {
  window.scrollTo({ top: 0, behavior: "smooth" });
}

/**
 * Scrolls the page to the bottom.
 */
function scrollToBottom() {
  window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
}

/**
 * Toggles the visibility of scroll-to-top/bottom buttons based on scroll position.
 */
function toggleScrollButtons() {
  const scrollButtons = document.querySelector(".scroll-buttons");
  if (scrollButtons) {
    scrollButtons.style.display = window.scrollY > 200 ? "flex" : "none";
  }
}

/**
 * Generates a random token string.
 * @returns {string} A randomly generated token.
 */
function generateRandomToken() {
  const characters =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_";
  const length = 48;
  let result = "sk-";
  for (let i = 0; i < length; i++) {
    result += characters.charAt(Math.floor(Math.random() * characters.length));
  }
  return result;
}

// --- Model Helper Functions ---
async function fetchModels() {
  if (cachedModelsList) {
    return cachedModelsList;
  }
  try {
    showNotification("正在从 /api/config/ui/models 加载模型列表...", "info");
    const response = await fetch("/api/config/ui/models");
    if (!response.ok) {
      const errorData = await response.text();
      throw new Error(`HTTP error ${response.status}: ${errorData}`);
    }
    const responseData = await response.json(); // Changed variable name to responseData
    // The backend returns an object like: { object: "list", data: [{id: "m1"}, {id: "m2"}], success: true }
    if (
      responseData &&
      responseData.success &&
      Array.isArray(responseData.data)
    ) {
      cachedModelsList = responseData.data; // Use responseData.data
      showNotification("模型列表加载成功", "success");
      return cachedModelsList;
    } else {
      console.error("Invalid model list format received:", responseData);
      throw new Error("模型列表格式无效或请求未成功");
    }
  } catch (error) {
    console.error("加载模型列表失败:", error);
    showNotification(`加载模型列表失败: ${error.message}`, "error");
    cachedModelsList = []; // Avoid repeated fetches on error for this session, or set to null to retry
    return [];
  }
}

function renderModelsInModal() {
  if (!modelHelperListContainer) return;
  if (!cachedModelsList) {
    modelHelperListContainer.innerHTML =
      '<p class="text-gray-400 text-sm italic">模型列表尚未加载。</p>';
    return;
  }

  const searchTerm = modelHelperSearchInput.value.toLowerCase();
  const filteredModels = cachedModelsList.filter((model) =>
    model.id.toLowerCase().includes(searchTerm)
  );

  modelHelperListContainer.innerHTML = ""; // Clear previous items

  if (filteredModels.length === 0) {
    modelHelperListContainer.innerHTML =
      '<p class="text-gray-400 text-sm italic">未找到匹配的模型。</p>';
    return;
  }

  filteredModels.forEach((model) => {
    const modelItemElement = document.createElement("button");
    modelItemElement.type = "button";
    modelItemElement.textContent = model.id;
    modelItemElement.className =
      "block w-full text-left px-4 py-2 rounded-md hover:bg-blue-100 focus:bg-blue-100 focus:outline-none transition-colors text-gray-700 hover:text-gray-800";
    // Add any other classes for styling, e.g., from existing modals or array items

    modelItemElement.addEventListener("click", () =>
      handleModelSelection(model.id)
    );
    modelHelperListContainer.appendChild(modelItemElement);
  });
}

async function openModelHelperModal() {
  if (!currentModelHelperTarget) {
    console.error("Model helper target not set.");
    showNotification("无法打开模型助手：目标未设置", "error");
    return;
  }

  await fetchModels(); // Ensure models are loaded
  renderModelsInModal(); // Render them (handles empty/error cases internally)

  if (modelHelperTitleElement) {
    if (
      currentModelHelperTarget.type === "input" &&
      currentModelHelperTarget.target
    ) {
      const label = document.querySelector(
        `label[for="${currentModelHelperTarget.target.id}"]`
      );
      modelHelperTitleElement.textContent = label
        ? `为 "${label.textContent.trim()}" 选择模型`
        : "选择模型";
    } else if (currentModelHelperTarget.type === "array") {
      modelHelperTitleElement.textContent = `为 ${currentModelHelperTarget.targetKey} 添加模型`;
    } else {
      modelHelperTitleElement.textContent = "选择模型";
    }
  }
  if (modelHelperSearchInput) modelHelperSearchInput.value = ""; // Clear search on open
  if (modelHelperModal) openModal(modelHelperModal);
}

function handleModelSelection(selectedModelId) {
  if (!currentModelHelperTarget) return;

  if (
    currentModelHelperTarget.type === "input" &&
    currentModelHelperTarget.target
  ) {
    const inputElement = currentModelHelperTarget.target;
    inputElement.value = selectedModelId;
    // If the input is a sensitive field, dispatch focusout to trigger masking behavior if needed
    if (inputElement.classList.contains(SENSITIVE_INPUT_CLASS)) {
      const event = new Event("focusout", { bubbles: true, cancelable: true });
      inputElement.dispatchEvent(event);
    }
    // Dispatch input event for any other listeners
    inputElement.dispatchEvent(new Event("input", { bubbles: true }));
  } else if (
    currentModelHelperTarget.type === "array" &&
    currentModelHelperTarget.targetKey
  ) {
    addArrayItemWithValue(
      currentModelHelperTarget.targetKey,
      selectedModelId
    );
  }

  if (modelHelperModal) closeModal(modelHelperModal);
  currentModelHelperTarget = null; // Reset target
}

// -- End Model Helper Functions --
