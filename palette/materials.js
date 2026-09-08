function colorFromHex(name, hex) {
  const normalized = /^#[0-9a-f]{6}$/i.test(hex) ? hex.slice(1) : "202020";
  return {
    name: name.trim() || "Custom",
    red: Number.parseInt(normalized.slice(0, 2), 16),
    green: Number.parseInt(normalized.slice(2, 4), 16),
    blue: Number.parseInt(normalized.slice(4, 6), 16),
  };
}

function openMaterialOptions(harness, wire = null) {
  const isWire = wire !== null;
  const settings = isWire ? wire.materials : harness.materialDefaults;
  const overrides = isWire ? wire.materialOverrides : null;
  const originalMaterials = JSON.parse(JSON.stringify(isWire ? overrides : settings));
  const profile = isWire
    ? harness.profiles.find((candidate) => candidate.profileId === wire.profileId) : null;
  const originalDiameterMm = profile?.diameterMm ?? null;
  let savedDiameterMm = originalDiameterMm;
  let hasAppliedChanges = false;
  let cancelInProgress = false;
  const catalog = currentState.catalog || {
    insulationMaterials: [], conductorMaterials: [], colors: [], stripePatterns: [],
  };
  const { dialog, form, heading, note, error, actions, cancel, save } = createOptionsDialog(
    "wire-options material-options",
  );
  const apply = document.createElement("button");
  const controls = {};
  heading.textContent = isWire
    ? `Wire options · ${wireLabel(wire)}` : "Harness wire-material defaults";
  note.textContent = isWire
    ? "Diameter applies to this wire. Checked material fields override this harness."
    : "These values are inherited by every wire unless that wire overrides a field.";
  form.append(heading, note);

  let diameter = null;
  if (isWire) {
    const diameterLabel = document.createElement("label");
    diameter = document.createElement("input");
    diameterLabel.textContent = lengthFieldLabel("Wire diameter");
    diameter.type = "number";
    diameter.className = "filter";
    diameter.step = "any";
    diameter.required = true;
    diameter.disabled = !profile;
    diameter.value = profile ? `${displayLength(profile.diameterMm)}` : "";
    if (!profile) diameter.placeholder = "Wire profile is missing";
    diameterLabel.append(diameter);
    form.append(diameterLabel);
  }

  const addAutocomplete = (wrapper, input, values, onChoose = () => {}) => {
    const menu = document.createElement("div");
    const available = values.map((value) => typeof value === "string" ? value : value.name);
    wrapper.classList.add("autocomplete");
    menu.className = "autocomplete-suggestions";
    menu.hidden = true;
    const renderSuggestions = () => {
      const query = input.value.trim().toLocaleLowerCase();
      const matches = available.filter(
        (value) => !query || value.toLocaleLowerCase().includes(query),
      ).slice(0, 16);
      menu.replaceChildren();
      matches.forEach((value) => {
        const choice = document.createElement("button");
        choice.type = "button";
        choice.textContent = value;
        choice.addEventListener("mousedown", (event) => event.preventDefault());
        choice.addEventListener("click", () => {
          input.value = value;
          menu.hidden = true;
          onChoose(value);
        });
        menu.append(choice);
      });
      menu.hidden = matches.length === 0;
    };
    input.addEventListener("click", renderSuggestions);
    input.addEventListener("input", renderSuggestions);
    input.addEventListener("blur", () => { menu.hidden = true; });
    wrapper.append(menu);
  };

  const addOverrideToggle = (header, key, update) => {
    if (!isWire) return null;
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    const text = document.createElement("span");
    checkbox.type = "checkbox";
    checkbox.checked = overrides[key] !== null;
    text.textContent = "Override";
    checkbox.addEventListener("change", update);
    label.append(checkbox, text);
    header.append(label);
    return checkbox;
  };

  const addTextField = (key, labelText, suggestions = [], multiline = false) => {
    const wrapper = document.createElement("div");
    const header = document.createElement("div");
    const label = document.createElement("strong");
    const input = document.createElement(multiline ? "textarea" : "input");
    wrapper.className = "material-field";
    header.className = "material-field-heading";
    label.textContent = labelText;
    if (!multiline) input.type = "text";
    input.className = "filter";
    input.value = settings[key] || "";
    const update = () => { input.disabled = Boolean(toggle && !toggle.checked); };
    const toggle = addOverrideToggle(header, key, update);
    header.prepend(label);
    update();
    wrapper.append(header, input);
    if (!multiline && suggestions.length) addAutocomplete(wrapper, input, suggestions);
    form.append(wrapper);
    controls[key] = { input, toggle };
  };

  addTextField("insulationMaterial", "Insulation material", catalog.insulationMaterials);
  addTextField("conductorMaterial", "Conductor material", catalog.conductorMaterials);

  const colorWrapper = document.createElement("div");
  const colorHeader = document.createElement("div");
  const colorLabel = document.createElement("strong");
  const colorRow = document.createElement("div");
  const colorPicker = document.createElement("input");
  const colorNameWrapper = document.createElement("div");
  const colorName = document.createElement("input");
  const appearanceSource = document.createElement("select");
  const libraryControls = document.createElement("div");
  const libraryLabel = document.createElement("label");
  const librarySelect = document.createElement("select");
  const appearanceLabel = document.createElement("label");
  const appearanceSelect = document.createElement("select");
  colorWrapper.className = "material-field";
  colorHeader.className = "material-field-heading";
  colorLabel.textContent = "Main insulation appearance";
  colorRow.className = "material-color-row";
  appearanceSource.className = "appearance-source";
  libraryControls.className = "appearance-library-controls";
  colorPicker.type = "color";
  colorPicker.value = settings.mainColor.hex;
  colorName.type = "text";
  colorName.className = "filter";
  colorName.value = settings.mainColor.name;
  [
    ["color", "Catalog or custom color"],
    ["library", "Fusion library appearance"],
  ].forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    appearanceSource.append(option);
  });
  appearanceSource.value = settings.appearance ? "library" : "color";
  librarySelect.title = "Fusion appearance library";
  appearanceSelect.title = "Fusion appearance";
  let loadedLibraries = [];
  let loadedAppearances = [];
  const setOptions = (select, values, selectedId, placeholder) => {
    select.replaceChildren();
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = placeholder;
    select.append(empty);
    values.forEach((item) => {
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = item.name;
      option.selected = item.id === selectedId;
      select.append(option);
    });
    select.value = values.some((item) => item.id === selectedId) ? selectedId : "";
  };
  const loadAppearances = async (libraryId, selectedId = "") => {
    setOptions(appearanceSelect, [], "", "Loading appearances…");
    appearanceSelect.disabled = true;
    const response = await send("get_library_appearances", { libraryId });
    if (!response.ok) throw new Error(response.error || "Could not read Fusion appearances.");
    loadedAppearances = response.appearances;
    setOptions(appearanceSelect, loadedAppearances, selectedId, "Select appearance");
    updateColor();
  };
  const loadAppearanceLibraries = async () => {
    try {
      const response = await send("get_appearance_libraries");
      if (!response.ok) {
        error.textContent = response.error || "Could not read appearance libraries.";
        setOptions(librarySelect, [], "", "Libraries unavailable");
        setOptions(appearanceSelect, [], "", "Appearances unavailable");
        return;
      }
      loadedLibraries = response.libraries;
      const selectedLibrary = settings.appearance?.libraryId || loadedLibraries[0]?.id || "";
      setOptions(librarySelect, loadedLibraries, selectedLibrary, "Select library");
      if (selectedLibrary && appearanceSource.value === "library") {
        await loadAppearances(selectedLibrary, settings.appearance?.appearanceId || "");
      }
      updateColor();
    } catch (failure) {
      error.textContent = failure.message;
      setOptions(librarySelect, [], "", "Libraries unavailable");
      setOptions(appearanceSelect, [], "", "Appearances unavailable");
    }
  };
  const updateColor = () => {
    const disabled = Boolean(colorToggle && !colorToggle.checked);
    const usesLibrary = appearanceSource.value === "library";
    appearanceSource.disabled = disabled;
    colorPicker.disabled = disabled || usesLibrary;
    colorName.disabled = disabled || usesLibrary;
    libraryControls.hidden = !usesLibrary;
    librarySelect.disabled = disabled || !usesLibrary || loadedLibraries.length === 0;
    appearanceSelect.disabled = disabled || !usesLibrary || loadedAppearances.length === 0;
  };
  const colorToggle = addOverrideToggle(colorHeader, "mainColor", updateColor);
  colorName.addEventListener("change", () => {
    const match = catalog.colors.find(
      (item) => item.name.toLocaleLowerCase() === colorName.value.trim().toLocaleLowerCase(),
    );
    if (match) colorPicker.value = match.hex;
  });
  colorPicker.addEventListener("input", () => {
    const match = catalog.colors.find(
      (item) => item.hex.toLocaleLowerCase() === colorPicker.value.toLocaleLowerCase(),
    );
    colorName.value = match?.name || "Custom";
  });
  appearanceSource.addEventListener("change", async () => {
    updateColor();
    if (appearanceSource.value === "library" && librarySelect.value
        && loadedAppearances.length === 0) {
      try {
        await loadAppearances(librarySelect.value, settings.appearance?.appearanceId || "");
      } catch (failure) {
        error.textContent = failure.message;
      }
    }
  });
  librarySelect.addEventListener("change", async () => {
    try {
      if (!librarySelect.value) {
        loadedAppearances = [];
        setOptions(appearanceSelect, [], "", "Select appearance");
        updateColor();
        return;
      }
      await loadAppearances(librarySelect.value);
    } catch (failure) {
      error.textContent = failure.message;
    }
  });
  colorHeader.prepend(colorLabel);
  updateColor();
  colorNameWrapper.append(colorName);
  colorRow.append(colorPicker, colorNameWrapper);
  libraryLabel.textContent = "Library";
  libraryLabel.append(librarySelect);
  appearanceLabel.textContent = "Appearance";
  appearanceLabel.append(appearanceSelect);
  libraryControls.append(libraryLabel, appearanceLabel);
  colorWrapper.append(colorHeader, appearanceSource, colorRow, libraryControls);
  addAutocomplete(colorNameWrapper, colorName, catalog.colors, (name) => {
    const match = catalog.colors.find((item) => item.name === name);
    if (match) colorPicker.value = match.hex;
  });
  form.append(colorWrapper);
  controls.mainColor = { colorPicker, colorName, toggle: colorToggle };

  const stripeWrapper = document.createElement("div");
  const stripeHeader = document.createElement("div");
  const stripeLabel = document.createElement("strong");
  const stripeList = document.createElement("div");
  const addStripe = document.createElement("button");
  stripeWrapper.className = "material-field";
  stripeHeader.className = "material-field-heading";
  stripeLabel.textContent = "Procedural stripes";
  stripeList.className = "stripe-list";
  addStripe.type = "button";
  addStripe.className = "button compact";
  addStripe.textContent = "+ Add stripe";

  const appendStripe = (stripe = null) => {
    const value = stripe || {
      color: catalog.colors.find((item) => item.name === "White")
        || { name: "White", hex: "#F5F5F5" },
      widthMm: 0.4, pattern: "longitudinal", angleDeg: 0, repeatMm: null,
    };
    const row = document.createElement("div");
    const picker = document.createElement("input");
    const values = document.createElement("div");
    const pattern = document.createElement("select");
    const width = document.createElement("input");
    const angle = document.createElement("input");
    const repeat = document.createElement("input");
    const remove = document.createElement("button");
    row.className = "stripe-row";
    picker.type = "color";
    picker.value = value.color.hex;
    values.className = "stripe-values";
    (catalog.stripePatterns.length
      ? catalog.stripePatterns : ["longitudinal", "dashed", "helical"]
    ).forEach((item) => {
      const option = document.createElement("option");
      option.value = item;
      option.textContent = item;
      option.selected = item === value.pattern;
      pattern.append(option);
    });
    const numericField = (labelText, input, initial) => {
      const label = document.createElement("label");
      label.textContent = labelText;
      input.type = "number";
      input.step = "any";
      input.value = initial == null ? "" : `${initial}`;
      label.append(input);
      return label;
    };
    const updateRepeat = () => {
      repeat.disabled = pattern.disabled || pattern.value === "longitudinal";
      if (pattern.value === "longitudinal") repeat.value = "";
    };
    pattern.addEventListener("change", updateRepeat);
    remove.type = "button";
    remove.className = "icon-button danger";
    remove.textContent = "×";
    remove.title = "Remove stripe";
    remove.addEventListener("click", () => row.remove());
    values.append(
      numericField(lengthFieldLabel("Width"), width, displayLength(value.widthMm)),
      numericField("Angle (deg)", angle, value.angleDeg),
      (() => {
        const label = document.createElement("label");
        label.textContent = "Pattern";
        label.append(pattern);
        return label;
      })(),
      numericField(lengthFieldLabel("Repeat"), repeat, displayLength(value.repeatMm)),
    );
    row.append(picker, values, remove);
    stripeList.append(row);
    updateRepeat();
    updateStripes();
  };
  const updateStripes = () => {
    const disabled = Boolean(stripeToggle && !stripeToggle.checked);
    addStripe.disabled = disabled;
    stripeList.querySelectorAll("input, select, button").forEach((input) => {
      input.disabled = disabled;
    });
    if (!disabled) {
      stripeList.querySelectorAll("select").forEach((pattern) => {
        const repeat = pattern.closest(".stripe-values").querySelector("label:last-child input");
        repeat.disabled = pattern.value === "longitudinal";
      });
    }
  };
  const stripeToggle = addOverrideToggle(stripeHeader, "stripes", updateStripes);
  stripeHeader.prepend(stripeLabel);
  (settings.stripes || []).forEach(appendStripe);
  addStripe.addEventListener("click", () => appendStripe());
  updateStripes();
  stripeWrapper.append(stripeHeader, stripeList, addStripe);
  form.append(stripeWrapper);

  addTextField("manufacturer", "Manufacturer");
  addTextField("partNumber", "Part number");
  addTextField("notes", "Notes", [], true);

  const readStripes = () => [...stripeList.children].map((row, index) => {
    const inputs = row.querySelectorAll("input");
    const pattern = row.querySelector("select").value;
    const width = canonicalLength(inputs[1].value);
    const angle = Number(inputs[2].value);
    const repeat = inputs[3].value.trim() === "" ? null : canonicalLength(inputs[3].value);
    if (!Number.isFinite(width) || width <= 0 || !Number.isFinite(angle)
        || (pattern !== "longitudinal" && (!Number.isFinite(repeat) || repeat <= 0))) {
      throw new Error(`Stripe ${index + 1} needs a positive width, finite angle, and pattern repeat.`);
    }
    const catalogColor = catalog.colors.find(
      (item) => item.hex.toLocaleLowerCase() === inputs[0].value.toLocaleLowerCase(),
    );
    return {
      color: colorFromHex(catalogColor?.name || "Custom", inputs[0].value),
      widthMm: width, pattern, angleDeg: angle, repeatMm: repeat,
    };
  });

  apply.type = "button";
  apply.className = "button";
  apply.textContent = "Apply";
  const applyMaterials = async (closeAfter) => {
    try {
      const diameterMm = isWire && profile ? canonicalLength(diameter.value) : null;
      if (isWire && profile && (!Number.isFinite(diameterMm) || diameterMm <= 0)) {
        error.textContent = `Enter a positive diameter in ${activeLengthUnit()}.`;
        return;
      }
      const fieldValue = (key) => {
        const control = controls[key];
        return isWire && !control.toggle.checked ? null : control.input.value;
      };
      let appearance = null;
      if ((!isWire || colorToggle.checked) && appearanceSource.value === "library") {
        const library = loadedLibraries.find((item) => item.id === librarySelect.value);
        const selected = loadedAppearances.find(
          (item) => item.id === appearanceSelect.value,
        );
        if (!library || !selected) {
          error.textContent = "Select a Fusion appearance library and appearance.";
          return;
        }
        appearance = {
          libraryId: library.id,
          libraryName: library.name,
          appearanceId: selected.id,
          appearanceName: selected.name,
        };
      }
      const materials = {
        insulationMaterial: fieldValue("insulationMaterial"),
        conductorMaterial: fieldValue("conductorMaterial"),
        mainColor: isWire && !colorToggle.checked ? null
          : colorFromHex(colorName.value, colorPicker.value),
        appearance: isWire && !colorToggle.checked ? null : appearance,
        stripes: isWire && !stripeToggle.checked ? null : readStripes(),
        manufacturer: fieldValue("manufacturer"),
        partNumber: fieldValue("partNumber"),
        notes: fieldValue("notes"),
      };
      if ((!isWire || materials.insulationMaterial !== null)
          && !materials.insulationMaterial.trim()) {
        error.textContent = "Insulation material must not be empty.";
        return;
      }
      if ((!isWire || materials.conductorMaterial !== null)
          && !materials.conductorMaterial.trim()) {
        error.textContent = "Conductor material must not be empty.";
        return;
      }
      apply.disabled = true;
      cancel.disabled = true;
      save.disabled = true;
      if (isWire && profile && diameterMm !== savedDiameterMm) {
        const diameterResponse = await send("set_wire_diameter", {
          harnessId: harness.harnessId, wireId: wire.wireId, diameterMm,
        });
        if (!diameterResponse.ok) {
          error.textContent = diameterResponse.error || "Could not save wire diameter.";
          return;
        }
        savedDiameterMm = diameterMm;
        hasAppliedChanges = true;
      }
      const response = await send(
        isWire ? "set_wire_material_overrides" : "set_harness_material_defaults",
        isWire
          ? { harnessId: harness.harnessId, wireId: wire.wireId, overrides: materials }
          : { harnessId: harness.harnessId, materials },
      );
      if (response.ok) {
        hasAppliedChanges = !closeAfter;
        error.textContent = closeAfter ? "" : "Applied.";
        if (closeAfter) dialog.close();
      }
      else error.textContent = response.error || "Could not save wire materials.";
    } catch (failure) {
      error.textContent = failure.message;
    } finally {
      apply.disabled = false;
      cancel.disabled = false;
      save.disabled = false;
    }
  };
  dialog.cancelOptions = async () => {
    if (cancelInProgress) return;
    if (!hasAppliedChanges) {
      dialog.close();
      return;
    }
    cancelInProgress = true;
    apply.disabled = true;
    cancel.disabled = true;
    save.disabled = true;
    error.textContent = "Restoring saved options…";
    try {
      if (isWire && profile && savedDiameterMm !== originalDiameterMm) {
        const diameterResponse = await send("set_wire_diameter", {
          harnessId: harness.harnessId,
          wireId: wire.wireId,
          diameterMm: originalDiameterMm,
        });
        if (!diameterResponse.ok) {
          error.textContent = diameterResponse.error || "Could not restore wire diameter.";
          return;
        }
        savedDiameterMm = originalDiameterMm;
      }
      const response = await send(
        isWire ? "set_wire_material_overrides" : "set_harness_material_defaults",
        isWire
          ? { harnessId: harness.harnessId, wireId: wire.wireId, overrides: originalMaterials }
          : { harnessId: harness.harnessId, materials: originalMaterials },
      );
      if (!response.ok) {
        error.textContent = response.error || "Could not restore wire materials.";
        return;
      }
      hasAppliedChanges = false;
      dialog.close();
    } catch (failure) {
      error.textContent = failure.message;
    } finally {
      cancelInProgress = false;
      apply.disabled = false;
      cancel.disabled = false;
      save.disabled = false;
    }
  };
  apply.addEventListener("click", () => applyMaterials(false));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    void applyMaterials(true);
  });
  dialog.addEventListener("close", () => dialog.remove());
  actions.append(cancel, apply, save);
  form.append(error, actions);
  dialog.append(form);
  document.body.append(dialog);
  dialog.showModal();
  void loadAppearanceLibraries();
}

function renderWireRoutes(harness) {
  const key = harnessKey(harness);
  const connections = new Map(
    harness.connections.map((connection) => [connection.connectionId, connection]),
  );
  const profiles = new Map(
    harness.profiles.map((profile) => [profile.profileId, profile]),
  );
  const pathways = new Map(
    harness.pathways.map((pathway) => [pathway.pathwayId, pathway]),
  );
  const container = document.createElement("div");
  const filter = document.createElement("input");
  const routes = document.createElement("div");
  container.className = "section-content";
  filter.className = "filter wire-filter";
  filter.type = "search";
  filter.placeholder = "Filter wire routes…";
  filter.setAttribute("aria-label", "Filter wire routes");
  filter.value = routeFilters.get(key) || "";
  filter.autocomplete = "off";
  const renderRoutes = () => {
    const query = filter.value.trim().toLocaleLowerCase();
    routeFilters.set(key, query);
    routes.replaceChildren();
    const visibleWires = harness.wires.filter((wire) => {
      const start = wire.startEndName || connections.get(wire.startConnectionId)?.name || "Missing End A";
      const end = wire.endEndName || connections.get(wire.endConnectionId)?.name || "Missing End B";
      const path = wire.orderedPathwayIds
        .map((id) => `${pathways.get(id)?.name || "Missing pathway"} ${pathwayDirection(pathways.get(id))}`)
        .join(" ");
      return `${wire.wireNumber} ${wireLabel(wire)} ${start} ${end} ${path}`
        .toLocaleLowerCase()
        .includes(query);
    });
    if (!visibleWires.length) {
      routes.append(emptyMessage(
        harness.wires.length ? "No wire routes match this filter." : "No wires defined yet.",
      ));
      return;
    }
    visibleWires.forEach((wire) => {
      const card = document.createElement("div");
      const profile = profiles.get(wire.profileId);
      const start = connections.get(wire.startConnectionId);
      const end = connections.get(wire.endConnectionId);
      const endAEditor = renderEndEditor(
        harness, [wire], connections, "start", `end-a-${wire.wireId}`,
      );
      const endBEditor = renderEndEditor(
        harness, [wire], connections, "end", `end-b-${wire.wireId}`,
      );
      card.className = "wire-route";
      card.dataset.wireId = wire.wireId;
      const details = document.createElement("div");
      details.className = "wire-details";
      details.id = `wire-details-${wire.wireId}`;
      details.hidden = !expandedSections.has(`wire:${harness.harnessId}:${wire.wireId}`);
      const optionsNode = document.createElement("button");
      optionsNode.type = "button";
      optionsNode.className = `route-node wire-options-button${profile ? "" : " missing"}`;
      optionsNode.textContent = `Wire options · ${profile ? `${displayLength(profile.diameterMm)} ${activeLengthUnit()}` : "missing diameter"}`
        + ` · ${wire.materials.mainColor.name} ${wire.materials.insulationMaterial}`
        + `${wire.materials.stripes.length ? ` · ${wire.materials.stripes.length} stripes` : ""}`;
      optionsNode.style.borderLeft = `8px solid ${wire.materials.mainColor.hex}`;
      optionsNode.title = "Edit wire diameter and material options";
      optionsNode.addEventListener("click", () => openMaterialOptions(harness, wire));
      details.append(
        renderWireRelationshipGraphic(
          harness,
          wire,
          connections,
          pathways,
          endAEditor,
          endBEditor,
        ),
        optionsNode,
        endAEditor,
        endBEditor,
      );
      card.append(wireHeader(
        harness, wire, details, !start?.hasLinkedGeometry || !end?.hasLinkedGeometry,
      ), details);
      routes.append(card);
    });
  };
  filter.addEventListener("input", renderRoutes);
  container.append(filter, routes);
  renderRoutes();
  return container;
}
