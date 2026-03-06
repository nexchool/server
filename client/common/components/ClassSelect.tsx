/**
 * Dropdown-style class selector for long lists.
 * Renders a touchable showing current selection; opens a modal with scrollable list.
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

interface ClassSelectProps {
  value: string | null;
  onChange: (id: string | null) => void;
  options: ClassOption[];
  placeholder?: string;
  allowEmpty?: boolean;
  emptyLabel?: string;
  label?: string;
  style?: object;
}

export function ClassSelect({
  value,
  onChange,
  options,
  placeholder = "Select class",
  allowEmpty = true,
  emptyLabel = "All",
  label,
  style,
}: ClassSelectProps) {
  const [modalVisible, setModalVisible] = useState(false);

  const displayOptions = options.map((c) => ({
    id: c.id,
    label: c.label ?? (c.section ? `${c.name}-${c.section}` : c.name ?? c.id),
  }));

  const selectedLabel = value
    ? displayOptions.find((o) => o.id === value)?.label ?? placeholder
    : emptyLabel;

  return (
    <View style={[styles.container, style]}>
      {label && <Text style={styles.label}>{label}</Text>}
      <TouchableOpacity
        style={styles.trigger}
        onPress={() => setModalVisible(true)}
        activeOpacity={0.7}
      >
        <Text style={styles.triggerText} numberOfLines={1}>
          {selectedLabel}
        </Text>
        <Ionicons name="chevron-down" size={20} color={Colors.textSecondary} />
      </TouchableOpacity>

      <Modal visible={modalVisible} transparent animationType="fade">
        <TouchableWithoutFeedback onPress={() => setModalVisible(false)}>
          <View style={styles.modalOverlay}>
            <View style={styles.modalContent} onStartShouldSetResponder={() => true}>
              <Text style={styles.modalTitle}>{label ?? "Select Class"}</Text>
              <FlatList
                data={
                  allowEmpty
                    ? [{ id: "__empty__", label: emptyLabel }, ...displayOptions]
                    : displayOptions
                }
                keyExtractor={(item) => item.id}
                renderItem={({ item }) => (
                  <TouchableOpacity
                    style={[
                      styles.modalItem,
                      (item.id === "__empty__" ? !value : value === item.id) &&
                        styles.modalItemActive,
                    ]}
                    onPress={() => {
                      onChange(item.id === "__empty__" ? null : item.id);
                      setModalVisible(false);
                    }}
                  >
                    <Text
                      style={[
                        styles.modalItemText,
                        (item.id === "__empty__" ? !value : value === item.id) &&
                          styles.modalItemTextActive,
                      ]}
                    >
                      {item.label}
                    </Text>
                  </TouchableOpacity>
                )}
                style={styles.modalList}
              />
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
  triggerText: { fontSize: 16, color: Colors.text, flex: 1 },
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
  modalTitle: {
    fontSize: 18,
    fontWeight: "600",
    color: Colors.text,
    padding: Spacing.lg,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
  },
  modalList: { maxHeight: 300 },
  modalItem: {
    padding: Spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
  },
  modalItemActive: { backgroundColor: Colors.backgroundSecondary },
  modalItemText: { fontSize: 16, color: Colors.text },
  modalItemTextActive: { fontWeight: "600", color: Colors.primary },
});
