/**
 * Multi-select class picker for fee structures.
 * Opens a modal with scrollable list; supports selecting multiple classes.
 */
import React, { useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Modal,
  FlatList,
  TouchableWithoutFeedback,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { Colors } from "@/common/constants/colors";
import { Spacing, Layout } from "@/common/constants/spacing";

export interface ClassOption {
  id: string;
  label: string;
  name?: string;
  section?: string;
}

interface ClassMultiSelectProps {
  value: string[];
  onChange: (ids: string[]) => void;
  options: ClassOption[];
  placeholder?: string;
  label?: string;
  style?: object;
}

export function ClassMultiSelect({
  value,
  onChange,
  options,
  placeholder = "Select classes",
  label,
  style,
}: ClassMultiSelectProps) {
  const [modalVisible, setModalVisible] = useState(false);
  const selectedSet = new Set(value);

  const toggleClass = (id: string) => {
    const next = new Set(selectedSet);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onChange(Array.from(next));
  };

  const displayOptions = options.map((c) => ({
    id: c.id,
    label: c.label ?? (c.section ? `${c.name}-${c.section}` : c.name ?? c.id),
  }));

  const selectedLabels = value
    .map((id) => displayOptions.find((o) => o.id === id)?.label)
    .filter(Boolean);

  const triggerText =
    selectedLabels.length > 0
      ? selectedLabels.join(", ")
      : placeholder;

  return (
    <View style={[styles.container, style]}>
      {label && <Text style={styles.label}>{label}</Text>}
      <TouchableOpacity
        style={styles.trigger}
        onPress={() => setModalVisible(true)}
        activeOpacity={0.7}
      >
        <Text style={styles.triggerText} numberOfLines={2}>
          {triggerText}
        </Text>
        <Ionicons name="chevron-down" size={20} color={Colors.textSecondary} />
      </TouchableOpacity>

      <Modal visible={modalVisible} transparent animationType="fade">
        <TouchableWithoutFeedback onPress={() => setModalVisible(false)}>
          <View style={styles.modalOverlay}>
            <View style={styles.modalContent} onStartShouldSetResponder={() => true}>
              <View style={styles.modalHeaderRow}>
                <View>
                  <Text style={styles.modalTitle}>
                    {label ?? "Select Classes"}
                  </Text>
                  <Text style={styles.modalHint}>
                    {value.length > 0
                      ? `${value.length} selected. Leave empty for all classes.`
                      : "Select multiple. Leave empty for all classes."}
                  </Text>
                </View>
                {value.length > 0 && (
                  <TouchableOpacity
                    onPress={() => onChange([])}
                    style={styles.clearBtn}
                  >
                    <Text style={styles.clearBtnText}>Clear</Text>
                  </TouchableOpacity>
                )}
              </View>
              <FlatList
                data={displayOptions}
                keyExtractor={(item) => item.id}
                renderItem={({ item }) => (
                  <TouchableOpacity
                    style={[
                      styles.modalItem,
                      selectedSet.has(item.id) && styles.modalItemActive,
                    ]}
                    onPress={() => toggleClass(item.id)}
                  >
                    <Ionicons
                      name={selectedSet.has(item.id) ? "checkbox" : "square-outline"}
                      size={22}
                      color={selectedSet.has(item.id) ? Colors.primary : Colors.textSecondary}
                      style={styles.checkIcon}
                    />
                    <Text
                      style={[
                        styles.modalItemText,
                        selectedSet.has(item.id) && styles.modalItemTextActive,
                      ]}
                    >
                      {item.label}
                    </Text>
                  </TouchableOpacity>
                )}
                style={styles.modalList}
              />
              <TouchableOpacity
                style={styles.doneBtn}
                onPress={() => setModalVisible(false)}
              >
                <Text style={styles.doneBtnText}>Done</Text>
              </TouchableOpacity>
            </View>
          </View>
        </TouchableWithoutFeedback>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {},
  label: { fontSize: 14, color: Colors.textSecondary, marginBottom: Spacing.sm },
  trigger: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    backgroundColor: Colors.backgroundSecondary,
    borderWidth: 1,
    borderColor: Colors.border,
    borderRadius: Layout.borderRadius.md,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.md,
    minHeight: 52,
  },
  triggerText: {
    fontSize: 16,
    color: Colors.text,
    flex: 1,
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.5)",
    justifyContent: "center",
    alignItems: "center",
  },
  modalContent: {
    backgroundColor: Colors.background,
    borderRadius: Layout.borderRadius.lg,
    width: "85%",
    maxHeight: "70%",
  },
  modalHeaderRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    padding: Spacing.lg,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
  },
  modalTitle: {
    fontSize: 18,
    fontWeight: "600",
    color: Colors.text,
  },
  modalHint: {
    fontSize: 12,
    color: Colors.textSecondary,
    marginTop: 2,
  },
  clearBtn: {
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
  },
  clearBtnText: {
    fontSize: 14,
    fontWeight: "600",
    color: Colors.primary,
  },
  modalList: { maxHeight: 280 },
  modalItem: {
    flexDirection: "row",
    alignItems: "center",
    padding: Spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
  },
  modalItemActive: { backgroundColor: Colors.backgroundSecondary },
  checkIcon: { marginRight: Spacing.sm },
  modalItemText: { fontSize: 16, color: Colors.text, flex: 1 },
  modalItemTextActive: { fontWeight: "600", color: Colors.primary },
  doneBtn: {
    padding: Spacing.lg,
    alignItems: "center",
    borderTopWidth: 1,
    borderTopColor: Colors.borderLight,
  },
  doneBtnText: { fontSize: 16, fontWeight: "600", color: Colors.primary },
});
