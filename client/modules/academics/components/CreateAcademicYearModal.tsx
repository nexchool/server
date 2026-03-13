import React, { useState, useEffect } from "react";
import {
  View,
  Text,
  StyleSheet,
  Modal,
  TouchableOpacity,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { Colors } from "@/common/constants/colors";
import { Spacing, Layout } from "@/common/constants/spacing";
import { academicYearService, type AcademicYear } from "../services/academicYearService";
import { DateField } from "@/common/components/DateField";

interface CreateAcademicYearModalProps {
  visible: boolean;
  onClose: () => void;
  onSuccess: (year: AcademicYear) => void;
}

export function CreateAcademicYearModal({
  visible,
  onClose,
  onSuccess,
}: CreateAcademicYearModalProps) {
  const [name, setName] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (visible) {
      setName("");
      setStartDate("");
      setEndDate("");
      setError(null);
    }
  }, [visible]);

  const handleSubmit = async () => {
    const n = name.trim();
    const sd = startDate.trim();
    const ed = endDate.trim();
    if (!n || !sd || !ed) {
      setError("Name, start date, and end date are required");
      return;
    }
    const startMatch = /^\d{4}-\d{2}-\d{2}$/.test(sd);
    const endMatch = /^\d{4}-\d{2}-\d{2}$/.test(ed);
    if (!startMatch || !endMatch) {
      setError("Dates must be in YYYY-MM-DD format");
      return;
    }
    if (new Date(sd) >= new Date(ed)) {
      setError("Start date must be before end date");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const created = await academicYearService.createAcademicYear({
        name: n,
        start_date: sd,
        end_date: ed,
        is_active: true,
      });
      onSuccess(created);
      onClose();
    } catch (e: any) {
      setError(e?.message ?? "Failed to create academic year");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal visible={visible} transparent animationType="fade">
      <KeyboardAvoidingView
        style={styles.overlay}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <TouchableOpacity
          style={styles.backdrop}
          activeOpacity={1}
          onPress={onClose}
        />
        <View style={styles.modal}>
          <View style={styles.header}>
            <Text style={styles.title}>Create Academic Year</Text>
            <TouchableOpacity onPress={onClose} style={styles.closeBtn}>
              <Ionicons name="close" size={24} color={Colors.text} />
            </TouchableOpacity>
          </View>

          {error && (
            <View style={styles.errorBox}>
              <Text style={styles.errorText}>{error}</Text>
            </View>
          )}

          <Text style={styles.label}>Name *</Text>
          <View style={styles.input}>
            <Text
              style={{
                fontSize: 16,
                color: name ? Colors.text : Colors.textTertiary,
              }}
              numberOfLines={1}
            >
              {name || "e.g. 2025-2026"}
            </Text>
          </View>

          <DateField
            label="Start Date *"
            value={startDate}
            onChange={setStartDate}
            placeholder="YYYY-MM-DD"
          />

          <DateField
            label="End Date *"
            value={endDate}
            onChange={setEndDate}
            placeholder="YYYY-MM-DD"
          />

          <TouchableOpacity
            style={[styles.submitBtn, loading && styles.submitBtnDisabled]}
            onPress={handleSubmit}
            disabled={loading}
          >
            {loading ? (
              <ActivityIndicator color="#FFF" />
            ) : (
              <Text style={styles.submitText}>Create</Text>
            )}
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    padding: Spacing.lg,
  },
  backdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(0,0,0,0.4)",
  },
  modal: {
    backgroundColor: Colors.background,
    borderRadius: Layout.borderRadius.md,
    padding: Spacing.lg,
    width: "100%",
    maxWidth: 360,
  },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: Spacing.md,
  },
  title: {
    fontSize: 18,
    fontWeight: "600",
    color: Colors.text,
  },
  closeBtn: { padding: Spacing.xs },
  errorBox: {
    backgroundColor: "#FFF0F0",
    padding: Spacing.sm,
    borderRadius: Layout.borderRadius.sm,
    marginBottom: Spacing.md,
    borderLeftWidth: 4,
    borderLeftColor: Colors.error,
  },
  errorText: { color: Colors.error, fontSize: 14 },
  label: {
    fontSize: 14,
    fontWeight: "500",
    color: Colors.text,
    marginBottom: Spacing.xs,
  },
  input: {
    borderWidth: 1,
    borderColor: Colors.borderLight,
    borderRadius: Layout.borderRadius.sm,
    padding: Spacing.md,
    fontSize: 16,
    color: Colors.text,
    backgroundColor: Colors.backgroundSecondary,
    marginBottom: Spacing.md,
  },
  submitBtn: {
    backgroundColor: Colors.primary,
    padding: Spacing.md,
    borderRadius: Layout.borderRadius.md,
    alignItems: "center",
    marginTop: Spacing.sm,
  },
  submitBtnDisabled: { opacity: 0.6 },
  submitText: { color: "#FFF", fontSize: 16, fontWeight: "600" },
});
