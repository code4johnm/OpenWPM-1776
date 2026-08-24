/* OpenWPM page-world JS instrumentation.
 * Injected via Playwright add_init_script before any page scripts.
 * Chromium V8 stack traces are parsed; Firefox stack format is not used.
 */
function getInstrumentJS(eventId, sendMessagesToLogger) {
  /*
   * Instrumentation helpers
   * (Inlined in order for jsInstruments to be easily exportable as a string)
   */

  // Counter to cap # of calls logged for each script/api combination
  const maxLogCount = 500;
  // logCounter
  const logCounter = new Object();
  // Prevent logging of gets arising from logging
  let inLog = false;
  // To keep track of the original order of events
  let ordinal = 0;

  // Options for JSOperation
  const JSOperation = {
    call: "call",
    get: "get",
    get_failed: "get(failed)",
    get_function: "get(function)",
    set: "set",
    set_failed: "set(failed)",
    set_prevented: "set(prevented)",
  };

  // Rough implementations of Object.getPropertyDescriptor and Object.getPropertyNames
  // See http://wiki.ecmascript.org/doku.php?id=harmony:extended_object_api
  Object.getPropertyDescriptor = function (subject, name) {
    if (subject === undefined) {
      throw new Error("Can't get property descriptor for undefined");
    }
    let pd = Object.getOwnPropertyDescriptor(subject, name);
    let proto = Object.getPrototypeOf(subject);
    while (pd === undefined && proto !== null) {
      pd = Object.getOwnPropertyDescriptor(proto, name);
      proto = Object.getPrototypeOf(proto);
    }
    return pd;
  };

  Object.getPropertyNames = function (subject) {
    if (subject === undefined) {
      throw new Error("Can't get property names for undefined");
    }
    let props = Object.getOwnPropertyNames(subject);
    let proto = Object.getPrototypeOf(subject);
    while (proto !== null) {
      props = props.concat(Object.getOwnPropertyNames(proto));
      proto = Object.getPrototypeOf(proto);
    }
    // FIXME: remove duplicate property names from props
    return props;
  };

  // debounce - from Underscore v1.6.0
  function debounce(func, wait, immediate = false) {
    let timeout;
    let args;
    let context;
    let timestamp;
    let result;

    const later = function () {
      const last = Date.now() - timestamp;
      if (last < wait) {
        timeout = setTimeout(later, wait - last);
      } else {
        timeout = null;
        if (!immediate) {
          result = func.apply(context, args);
          context = args = null;
        }
      }
    };

    return function () {
      context = this; // eslint-disable-line @typescript-eslint/no-this-alias
      args = arguments; // eslint-disable-line prefer-rest-params
      timestamp = Date.now();
      const callNow = immediate && !timeout;
      if (!timeout) {
        timeout = setTimeout(later, wait);
      }
      if (callNow) {
        result = func.apply(context, args);
        context = args = null;
      }

      return result;
    };
  }

  // Recursively generates a path for an element
  function getPathToDomElement(element, visibilityAttr = false) {
    if (element === document.body) {
      return element.tagName;
    }
    if (element.parentNode === null) {
      return "NULL/" + element.tagName;
    }

    let siblingIndex = 1;
    const siblings = element.parentNode.childNodes;
    for (const sibling of siblings) {
      if (sibling === element) {
        let path = getPathToDomElement(element.parentNode, visibilityAttr);
        path += "/" + element.tagName + "[" + siblingIndex;
        path += "," + element.id;
        path += "," + element.className;
        if (visibilityAttr) {
          path += "," + element.hidden;
          path += "," + element.style.display;
          path += "," + element.style.visibility;
        }
        if (element.tagName === "A") {
          path += "," + element.href;
        }
        path += "]";
        return path;
      }
      if (sibling.nodeType === 1 && sibling.tagName === element.tagName) {
        siblingIndex++;
      }
    }
  }

  // Helper for JSONifying objects
  function serializeObject(
    object,
    stringifyFunctions = false,
  ) {
    // Handle permissions errors
    try {
      if (object === null) {
        return "null";
      }
      if (typeof object === "function") {
        return stringifyFunctions ? object.toString() : "FUNCTION";
      }
      if (typeof object !== "object") {
        return object;
      }
      const seenObjects = [];
      return JSON.stringify(object, function (key, value) {
        if (value === null) {
          return "null";
        }
        if (typeof value === "function") {
          return stringifyFunctions ? value.toString() : "FUNCTION";
        }
        if (typeof value === "object") {
          // Remove wrapping on content objects
          if ("wrappedJSObject" in value) {
            value = value.wrappedJSObject;
          }

          // Serialize DOM elements
          if (value instanceof HTMLElement) {
            return getPathToDomElement(value);
          }

          // Prevent serialization cycles
          if (key === "" || !seenObjects.includes(value)) {
            seenObjects.push(value);
            return value;
          } else {
            return typeof value;
          }
        }
        return value;
      });
    } catch (error) {
      console.log("OpenWPM: SERIALIZATION ERROR: " + error);
      return "SERIALIZATION ERROR: " + error;
    }
  }

  function updateCounterAndCheckIfOver(scriptUrl, symbol) {
    const key = scriptUrl + "|" + symbol;
    if (key in logCounter && logCounter[key] >= maxLogCount) {
      return true;
    } else if (!(key in logCounter)) {
      logCounter[key] = 1;
    } else {
      logCounter[key] += 1;
    }
    return false;
  }

  // For gets, sets, etc. on a single value
  function logValue(
    instrumentedVariableName,
    value,
    operation, // from JSOperation object please
    callContext,
    logSettings,
  ) {
    if (inLog) {
      return;
    }
    inLog = true;

    const overLimit = updateCounterAndCheckIfOver(
      callContext.scriptUrl,
      instrumentedVariableName,
    );
    if (overLimit) {
      inLog = false;
      return;
    }

    const msg = {
      operation,
      symbol: instrumentedVariableName,
      value: serializeObject(value, logSettings.logFunctionsAsStrings),
      scriptUrl: callContext.scriptUrl,
      scriptLine: callContext.scriptLine,
      scriptCol: callContext.scriptCol,
      funcName: callContext.funcName,
      scriptLocEval: callContext.scriptLocEval,
      callStack: callContext.callStack,
      ordinal: ordinal++,
    };

    try {
      send("logValue", msg);
    } catch (error) {
      console.log("OpenWPM: Unsuccessful value log!");
      logErrorToConsole(error);
    }

    inLog = false;
  }

  // For functions
  function logCall(
    instrumentedFunctionName,
    args,
    callContext,
    logSettings,
  ) {
    if (inLog) {
      return;
    }
    inLog = true;

    const overLimit = updateCounterAndCheckIfOver(
      callContext.scriptUrl,
      instrumentedFunctionName,
    );
    if (overLimit) {
      inLog = false;
      return;
    }

    try {
      // Convert special arguments array to a standard array for JSONifying
      const serialArgs = [];
      for (const arg of args) {
        serialArgs.push(
          serializeObject(arg, logSettings.logFunctionsAsStrings),
        );
      }
      const msg = {
        operation: JSOperation.call,
        symbol: instrumentedFunctionName,
        args: serialArgs,
        value: "",
        scriptUrl: callContext.scriptUrl,
        scriptLine: callContext.scriptLine,
        scriptCol: callContext.scriptCol,
        funcName: callContext.funcName,
        scriptLocEval: callContext.scriptLocEval,
        callStack: callContext.callStack,
        ordinal: ordinal++,
      };
      send("logCall", msg);
    } catch (error) {
      console.log(
        "OpenWPM: Unsuccessful call log: " + instrumentedFunctionName,
      );
      logErrorToConsole(error);
    }
    inLog = false;
  }

  function logErrorToConsole(error, context = false) {
    console.error("OpenWPM: Error name: " + error.name);
    console.error("OpenWPM: Error message: " + error.message);
    console.error("OpenWPM: Error filename: " + error.fileName);
    console.error("OpenWPM: Error line number: " + error.lineNumber);
    console.error("OpenWPM: Error stack: " + error.stack);
    if (context) {
      console.error("OpenWPM: Error context: " + JSON.stringify(context));
    }
  }

  // Helper to get originating script urls
  function getStackTrace() {
    let stack;

    try {
      throw new Error();
    } catch (err) {
      stack = err.stack;
    }

    return stack;
  }

  // from http://stackoverflow.com/a/5202185
  const rsplit = function (source, sep, maxsplit) {
    const split = source.split(sep);
    return maxsplit
      ? [split.slice(0, -maxsplit).join(sep)].concat(split.slice(-maxsplit))
      : split;
  };


  function parseV8Frame(line) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("at ")) {
      // Firefox-style: FUNC@FILE:LINE:COL
      if (trimmed.includes("@")) {
        const at = trimmed.indexOf("@");
        const funcName = trimmed.slice(0, at);
        const rest = trimmed.slice(at + 1);
        const items = rsplit(rest, ":", 2);
        if (items.length >= 3) {
          return {
            funcName,
            scriptUrl: items[0],
            scriptLine: items[items.length - 2],
            scriptCol: items[items.length - 1],
          };
        }
      }
      return null;
    }
    const body = trimmed.slice(3);
    let m = body.match(/^(.*?)\s+\((.+):(\d+):(\d+)\)$/);
    if (m) {
      return { funcName: m[1], scriptUrl: m[2], scriptLine: m[3], scriptCol: m[4] };
    }
    m = body.match(/^(.*?)\s+\((.+)\)$/);
    if (m) {
      return { funcName: m[1], scriptUrl: m[2], scriptLine: "", scriptCol: "" };
    }
    m = body.match(/^(.*):(\d+):(\d+)$/);
    if (m) {
      return { funcName: "", scriptUrl: m[1], scriptLine: m[2], scriptCol: m[3] };
    }
    return { funcName: "", scriptUrl: body, scriptLine: "", scriptCol: "" };
  }

  function isInstrumentationFrame(frame) {
    const blob = (frame.funcName + " " + frame.scriptUrl).toLowerCase();
    return (
      blob.includes("getstacktrace") ||
      blob.includes("getoriginatingscriptcontext") ||
      blob.includes("parsev8frame") ||
      blob.includes("instrumentfunction") ||
      blob.includes("instrumentobject") ||
      blob.includes("logvalue") ||
      blob.includes("logcall") ||
      blob.includes("__playwright") ||
      blob.includes("__pw_") ||
      frame.scriptUrl === "<anonymous>" ||
      frame.scriptUrl.indexOf("pptr:") === 0
    );
  }


  function parseV8Frame(line) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("at ")) {
      // Firefox-style: FUNC@FILE:LINE:COL
      if (trimmed.includes("@")) {
        const at = trimmed.indexOf("@");
        const funcName = trimmed.slice(0, at);
        const rest = trimmed.slice(at + 1);
        const items = rsplit(rest, ":", 2);
        if (items.length >= 3) {
          return {
            funcName,
            scriptUrl: items[0],
            scriptLine: items[items.length - 2],
            scriptCol: items[items.length - 1],
          };
        }
      }
      return null;
    }
    const body = trimmed.slice(3);
    let m = body.match(/^(.*?)\s+\((.+):(\d+):(\d+)\)$/);
    if (m) {
      return { funcName: m[1], scriptUrl: m[2], scriptLine: m[3], scriptCol: m[4] };
    }
    m = body.match(/^(.*?)\s+\((.+)\)$/);
    if (m) {
      return { funcName: m[1], scriptUrl: m[2], scriptLine: "", scriptCol: "" };
    }
    m = body.match(/^(.*):(\d+):(\d+)$/);
    if (m) {
      return { funcName: "", scriptUrl: m[1], scriptLine: m[2], scriptCol: m[3] };
    }
    return { funcName: "", scriptUrl: body, scriptLine: "", scriptCol: "" };
  }

  function isInstrumentationFrame(frame) {
    const blob = (frame.funcName + " " + frame.scriptUrl).toLowerCase();
    return (
      blob.includes("getstacktrace") ||
      blob.includes("getoriginatingscriptcontext") ||
      blob.includes("parsev8frame") ||
      blob.includes("instrumentfunction") ||
      blob.includes("instrumentobject") ||
      blob.includes("logvalue") ||
      blob.includes("logcall") ||
      blob.includes("__playwright") ||
      blob.includes("__pw_") ||
      frame.scriptUrl === "<anonymous>" ||
      frame.scriptUrl.indexOf("pptr:") === 0
    );
  }


  function getOriginatingScriptContext(getCallStack = false) {
    const empty_context = {
      scriptUrl: "",
      scriptLine: "",
      scriptCol: "",
      funcName: "",
      scriptLocEval: "",
      callStack: "",
    };
    let raw;
    try {
      raw = getStackTrace();
    } catch (e) {
      return empty_context;
    }
    if (!raw) {
      return empty_context;
    }
    const trace = raw.trim().split("\n");
    const frames = [];
    for (const line of trace) {
      const parsed = parseV8Frame(line);
      if (parsed) {
        frames.push(parsed);
      }
    }
    const caller = frames.find((f) => !isInstrumentationFrame(f));
    if (!caller) {
      return empty_context;
    }
    let scriptUrl = caller.scriptUrl || "";
    let scriptLocEval = "";
    const lineNoIdx = scriptUrl.indexOf(" line ");
    if (lineNoIdx !== -1) {
      scriptLocEval = scriptUrl.slice(lineNoIdx + 1);
      scriptUrl = scriptUrl.slice(0, lineNoIdx);
    } else {
      // V8 eval frames: eval at NAME (file:line:col)
      const evalMatch = scriptUrl.match(/eval at .* \((.+):(\d+):(\d+)\)$/);
      if (evalMatch) {
        scriptLocEval = "eval";
      }
    }
    const callStack = getCallStack
      ? frames
          .filter((f) => !isInstrumentationFrame(f))
          .map((f) =>
            f.funcName
              ? f.funcName + "@" + f.scriptUrl + ":" + f.scriptLine + ":" + f.scriptCol
              : f.scriptUrl + ":" + f.scriptLine + ":" + f.scriptCol,
          )
          .join("\n")
          .trim()
      : "";
    return {
      scriptUrl,
      scriptLine: caller.scriptLine,
      scriptCol: caller.scriptCol,
      funcName: caller.funcName || "",
      scriptLocEval,
      callStack,
    };
  }

  function isObject(object, propertyName) {
    let property;
    try {
      property = object[propertyName];
    } catch {
      return false;
    }
    if (property === null) {
      // null is type "object"
      return false;
    }
    return typeof property === "object";
  }

  // Log calls to a given function
  // This helper function returns a wrapper around `func` which logs calls
  // to `func`. `objectName` and `methodName` are used strictly to identify
  // which object method `func` is coming from in the logs
  function instrumentFunction(
    objectName,
    methodName,
    func,
    logSettings,
  ) {
    return function () {
      const callContext = getOriginatingScriptContext(logSettings.logCallStack);
      logCall(
        objectName + "." + methodName,
        arguments, // eslint-disable-line prefer-rest-params
        callContext,
        logSettings,
      );
      // eslint-disable-next-line prefer-rest-params
      return func.apply(this, arguments);
    };
  }

  // Log properties of prototypes and objects
  function instrumentObjectProperty(
    object,
    objectName,
    propertyName,
    logSettings,
  ) {
    if (
      !object ||
      !objectName ||
      !propertyName ||
      propertyName === "undefined"
    ) {
      throw new Error(
        `Invalid request to instrumentObjectProperty.
        Object: ${object}
        objectName: ${objectName}
        propertyName: ${propertyName}
        `,
      );
    }

    // Store original descriptor in closure
    const propDesc = Object.getPropertyDescriptor(object, propertyName);

    // Property descriptor must exist unless we are instrumenting a nonExisting property
    if (
      !propDesc &&
      !logSettings.nonExistingPropertiesToInstrument.includes(propertyName)
    ) {
      console.error(
        "Property descriptor not found for",
        objectName,
        propertyName,
        object,
      );
      return;
    }

    // Property descriptor for undefined properties
    let undefinedPropValue;
    const undefinedPropDesc = {
      get: () => {
        return undefinedPropValue;
      },
      set: (value) => {
        undefinedPropValue = value;
      },
      enumerable: false,
    };

    // Instrument data or accessor property descriptors
    const originalGetter = propDesc ? propDesc.get : undefinedPropDesc.get;
    const originalSetter = propDesc ? propDesc.set : undefinedPropDesc.set;
    let originalValue = propDesc ? propDesc.value : undefinedPropValue;

    // We overwrite both data and accessor properties as an instrumented
    // accessor property
    Object.defineProperty(object, propertyName, {
      configurable: true,
      get: (function () {
        return function () {
          let origProperty;
          const callContext = getOriginatingScriptContext(
            logSettings.logCallStack,
          );
          const instrumentedVariableName = `${objectName}.${propertyName}`;

          // get original value
          if (!propDesc) {
            // if undefined property
            origProperty = undefinedPropValue;
          } else if (originalGetter) {
            // if accessor property
            origProperty = originalGetter.call(this);
          } else if ("value" in propDesc) {
            // if data property
            origProperty = originalValue;
          } else {
            console.error(
              `Property descriptor for ${instrumentedVariableName} doesn't have getter or value?`,
            );
            logValue(
              instrumentedVariableName,
              "",
              JSOperation.get_failed,
              callContext,
              logSettings,
            );
            return;
          }

          // Log `gets` except those that have instrumented return values
          // * All returned functions are instrumented with a wrapper
          // * Returned objects may be instrumented if recursive
          //   instrumentation is enabled and this isn't at the depth limit.
          if (typeof origProperty === "function") {
            if (logSettings.logFunctionGets) {
              logValue(
                instrumentedVariableName,
                origProperty,
                JSOperation.get_function,
                callContext,
                logSettings,
              );
            }
            const instrumentedFunctionWrapper = instrumentFunction(
              objectName,
              propertyName,
              origProperty,
              logSettings,
            );
            // Restore the original prototype and constructor so that instrumented classes remain intact
            // TODO: This may have introduced prototype pollution as per https://github.com/openwpm/OpenWPM/issues/471
            if (origProperty.prototype) {
              instrumentedFunctionWrapper.prototype = origProperty.prototype;
              if (origProperty.prototype.constructor) {
                instrumentedFunctionWrapper.prototype.constructor =
                  origProperty.prototype.constructor;
              }
            }
            return instrumentedFunctionWrapper;
          } else if (
            typeof origProperty === "object" &&
            logSettings.recursive &&
            logSettings.depth > 0
          ) {
            return origProperty;
          } else {
            logValue(
              instrumentedVariableName,
              origProperty,
              JSOperation.get,
              callContext,
              logSettings,
            );
            return origProperty;
          }
        };
      })(),
      set: (function () {
        return function (value) {
          const callContext = getOriginatingScriptContext(
            logSettings.logCallStack,
          );
          const instrumentedVariableName = `${objectName}.${propertyName}`;
          let returnValue;

          // Prevent sets for functions and objects if enabled
          if (
            logSettings.preventSets &&
            (typeof originalValue === "function" ||
              typeof originalValue === "object")
          ) {
            logValue(
              instrumentedVariableName,
              value,
              JSOperation.set_prevented,
              callContext,
              logSettings,
            );
            return value;
          }

          // set new value to original setter/location
          if (originalSetter) {
            // if accessor property
            returnValue = originalSetter.call(this, value);
          } else if ("value" in propDesc) {
            inLog = true;
            if (Object.prototype.isPrototypeOf.call(object, this)) {
              Object.defineProperty(this, propertyName, {
                value,
              });
            } else {
              originalValue = value;
            }
            returnValue = value;
            inLog = false;
          } else {
            console.error(
              `Property descriptor for ${instrumentedVariableName} doesn't have setter or value?`,
            );
            logValue(
              instrumentedVariableName,
              value,
              JSOperation.set_failed,
              callContext,
              logSettings,
            );
            return value;
          }
          logValue(
            instrumentedVariableName,
            value,
            JSOperation.set,
            callContext,
            logSettings,
          );
          return returnValue;
        };
      })(),
    });
  }

  function instrumentObject(
    object,
    instrumentedName,
    logSettings,
  ) {
    // Set propertiesToInstrument to null to force no properties to be instrumented.
    // (this is used in testing for example)
    let propertiesToInstrument;
    if (logSettings.propertiesToInstrument === null) {
      propertiesToInstrument = [];
    } else if (logSettings.propertiesToInstrument.length === 0) {
      try {
        propertiesToInstrument = Object.getPropertyNames(object);
      } catch (e) {
        console.warn(
          `OpenWPM: Cannot enumerate properties of ${instrumentedName}:`,
          e,
        );
        propertiesToInstrument = [];
      }
    } else {
      propertiesToInstrument = logSettings.propertiesToInstrument;
    }
    for (const propertyName of propertiesToInstrument) {
      if (logSettings.excludedProperties.includes(propertyName)) {
        continue;
      }
      // If `recursive` flag set we want to recursively instrument any
      // object properties that aren't the prototype object.
      if (
        logSettings.recursive &&
        logSettings.depth > 0 &&
        isObject(object, propertyName) &&
        propertyName !== "__proto__"
      ) {
        const newInstrumentedName = `${instrumentedName}.${propertyName}`;
        const newLogSettings = { ...logSettings };
        newLogSettings.depth = logSettings.depth - 1;
        newLogSettings.propertiesToInstrument = [];
        instrumentObject(
          object[propertyName],
          newInstrumentedName,
          newLogSettings,
        );
      }
      try {
        instrumentObjectProperty(
          object,
          instrumentedName,
          propertyName,
          logSettings,
        );
      } catch (error) {
        if (
          error instanceof TypeError &&
          error.message.includes("can't redefine non-configurable property")
        ) {
          console.warn(
            `Cannot instrument non-configurable property: ${instrumentedName}:${propertyName}`,
          );
        } else {
          logErrorToConsole(error, { instrumentedName, propertyName });
        }
      }
    }
    for (const propertyName of logSettings.nonExistingPropertiesToInstrument) {
      if (logSettings.excludedProperties.includes(propertyName)) {
        continue;
      }
      try {
        instrumentObjectProperty(
          object,
          instrumentedName,
          propertyName,
          logSettings,
        );
      } catch (error) {
        logErrorToConsole(error, { instrumentedName, propertyName });
      }
    }
  }

  const sendFactory = function (eventId, $sendMessagesToLogger) {
    let messages = [];
    // debounce sending queued messages
    const send = debounce(function () {
      $sendMessagesToLogger(eventId, messages);

      // clear the queue
      messages = [];
    }, 100);

    return function (msgType, msg) {
      // queue the message
      messages.push({ type: msgType, content: msg });
      send();
    };
  };

  const send = sendFactory(eventId, sendMessagesToLogger);

  function instrumentJS(JSInstrumentRequests) {
    // The JS Instrument Requests are setup and validated python side
    // including setting defaults for logSettings.

    // More details about how this function is invoked are in
    // content/javascript-instrument-content-scope.ts
    JSInstrumentRequests.forEach(function (item) {
      let targetObject;
      try {
        targetObject = eval(item.object);
      } catch (e) {
        console.warn(
          `OpenWPM: eval failed for instrument target: ${item.object}`,
          e,
        );
        targetObject = undefined;
      }

      if (targetObject !== undefined) {
        try {
          instrumentObject(
            targetObject,
            item.instrumentedName,
            item.logSettings,
          );
        } catch (e) {
          console.warn(
            `OpenWPM: instrumentObject failed for ${item.instrumentedName}`,
            e,
          );
        }
      }
    });
  }

  // This whole function getInstrumentJS returns just the function `instrumentJS`.
  return instrumentJS;
}


(function bootstrapOpenWPMJSInstrument() {
  const settings = window.__OPENWPM_JS_SETTINGS__;
  if (!settings || !settings.length) {
    return;
  }
  const pending = [];
  let flushTimer = null;
  function sendMessagesToLogger(_eventId, messages) {
    try {
      if (typeof window.__openwpm_js_log__ === "function") {
        window.__openwpm_js_log__(messages);
      } else {
        pending.push(messages);
      }
    } catch (e) {
      console.error("OpenWPM: failed to send JS instrumentation", e);
    }
  }
  window.__openwpm_js_flush__ = function () {
    if (pending.length && typeof window.__openwpm_js_log__ === "function") {
      pending.splice(0).forEach((m) => window.__openwpm_js_log__(m));
    }
  };
  const instrumentJS = getInstrumentJS("openwpm", sendMessagesToLogger);
  instrumentJS(settings);
  if (window.__OPENWPM_JS_TESTING__) {
    window.instrumentJS = instrumentJS;
  }
})();
