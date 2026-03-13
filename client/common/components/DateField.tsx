import React, { useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Modal,
  Platform,
  TouchableWithoutFeedback,
  Dimensions,
} from "react-native";
import DateTimePicker, {
  DateTimePickerEvent,
} from "@react-native-community/datetimepicker";
import { Ionicons } from "@expo/vector-icons";
import { Colors } from "@/common/constants/colors";
import { Spacing, Layout } from "@/common/constants/spacing";

export interface DateFieldProps {
  label?: string;
  value?: string | null;
  onChange: (value: string) => void;
  placeholder?: string;
  minimumDate?: Date;
  maximumDate?: Date;
  error?: string;
  disabled?: boolean;
  /** Use when this field is inside another Modal to avoid nested modals (picker shown as overlay instead). */
  useOverlayInsideModal?: boolean;
}

function parseIsoDate(value?: string | null): Date {
  if (!value) return new Date();
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return new Date();
  return d;
}

function toIsoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function formatDisplay(value?: string | null): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  try {
    return d.toLocaleDateString("en-IN", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  } catch {
    return value;
  }
}

function PickerContent({
  label,
  tempDate,
  minimumDate,
  maximumDate,
  onChange,
  onClose,
  onConfirm,
}: {
  label?: string;
  tempDate: Date;
  minimumDate?: Date;
  maximumDate?: Date;
  onChange: (e: DateTimePickerEvent, d?: Date) => void;
  onClose: () => void;
  onConfirm: () => void;
}) {
  return (
    <View style={styles.modalContent} onStartShouldSetResponder={() => true}>
      <View style={styles.modalHeader}>
        <Text style={styles.modalTitle}>{label || "Select date"}</Text>
        <TouchableOpacity onPress={onClose} style={styles.closeBtn}>
          <Ionicons name="close" size={22} color={Colors.text} />
        </TouchableOpacity>
      </View>
      <View style={styles.pickerContainer}>
        <DateTimePicker
          mode="date"
          value={tempDate}
          onChange={onChange}
          minimumDate={minimumDate}
          maximumDate={maximumDate}
          display={Platform.OS === "ios" ? "spinner" : "calendar"}
        />
      </View>
      {Platform.OS === "ios" && (
        <View style={styles.modalFooter}>
          <TouchableOpacity
            style={styles.footerBtnSecondary}
            onPress={onClose}
          >
            <Text style={styles.footerBtnSecondaryText}>Cancel</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.footerBtnPrimary}
            onPress={onConfirm}
          >
            <Text style={styles.footerBtnPrimaryText}>Done</Text>
          </TouchableOpacity>
        </View>
      )}
    </View>
  );
}

export function DateField({
  label,
  value,
  onChange,
  placeholder = "Select date",
  minimumDate,
  maximumDate,
  error,
  disabled,
  useOverlayInsideModal = false,
}: DateFieldProps) {
  const [open, setOpen] = useState(false);
  const [tempDate, setTempDate] = useState<Date>(parseIsoDate(value));

  const handleOpen = () => {
    if (disabled) return;
    setTempDate(parseIsoDate(value));
    setOpen(true);
  };

  const handleClose = () => setOpen(false);

  const handleChange = (_event: DateTimePickerEvent, date?: Date) => {
    if (!date) return;
    if (Platform.OS === "android") {
      setOpen(false);
      onChange(toIsoDate(date));
    } else {
      setTempDate(date);
    }
  };

  const handleConfirm = () => {
    onChange(toIsoDate(tempDate));
    setOpen(false);
  };

  const displayText = formatDisplay(value);

  const pickerContent = (
    <PickerContent
      label={label}
      tempDate={tempDate}
      minimumDate={minimumDate}
      maximumDate={maximumDate}
      onChange={handleChange}
      onClose={handleClose}
      onConfirm={handleConfirm}
    />
  );

  return (
    <View style={styles.container}>
      {label && <Text style={styles.label}>{label}</Text>}
      <TouchableOpacity
        style={[
          styles.trigger,
          !!error && styles.triggerError,
          disabled && styles.triggerDisabled,
        ]}
        activeOpacity={0.7}
        onPress={handleOpen}
        disabled={disabled}
      >
        <Text
          style={[
            styles.triggerText,
            !displayText && styles.placeholderText,
          ]}
          numberOfLines={1}
        >
          {displayText || placeholder}
        </Text>
        <Ionicons
          name="calendar-outline"
          size={18}
          color={Colors.textSecondary}
        />
      </TouchableOpacity>
      {error && <Text style={styles.errorText}>{error}</Text>}

      {useOverlayInsideModal ? (
        open ? (
          <View style={styles.overlayContainer} pointerEvents="box-none">
            <TouchableWithoutFeedback onPress={handleClose}>
              <View style={styles.overlayBackdrop} />
            </TouchableWithoutFeedback>
            <View style={styles.overlayCenter}>{pickerContent}</View>
          </View>
        ) : null
      ) : (
        <Modal
          visible={open}
          transparent
          animationType="fade"
          onRequestClose={handleClose}
        >
          <View style={styles.modalOverlay}>
            {pickerContent}
          </View>
        </Modal>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    marginBottom: Spacing.md,
  },
  label: {
    fontSize: 13,
    fontWeight: "600",
    color: Colors.textSecondary,
    marginBottom: Spacing.xs,
    textTransform: "uppercase",
    letterSpacing: 0.4,
  },
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
    minHeight: 48,
  },
  triggerError: {
    borderColor: Colors.error,
  },
  triggerDisabled: {
    opacity: 0.55,
  },
  triggerText: {
    flex: 1,
    fontSize: 15,
    color: Colors.text,
    marginRight: Spacing.sm,
  },
  placeholderText: {
    color: Colors.textTertiary,
  },
  errorText: {
    marginTop: 4,
    fontSize: 12,
    color: Colors.error,
  },
  overlayContainer: {
    position: "absolute",
    left: 0,
    top: 0,
    right: 0,
    bottom: 0,
    width: Dimensions.get("window").width,
    height: Dimensions.get("window").height,
    zIndex: 9999,
    justifyContent: "center",
    alignItems: "center",
    padding: Spacing.lg,
  },
  overlayBackdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: Colors.overlay,
  },
  overlayCenter: {
    alignSelf: "center",
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: Colors.overlay,
    justifyContent: "center",
    alignItems: "center",
    padding: Spacing.lg,
  },
  modalContent: {
    width: "100%",
    maxWidth: 360,
    borderRadius: Layout.borderRadius.lg,
    backgroundColor: Colors.background,
    overflow: "hidden",
  },
  modalHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: Spacing.lg,
    paddingVertical: Spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
  },
  modalTitle: {
    fontSize: 16,
    fontWeight: "600",
    color: Colors.text,
  },
  closeBtn: {
    padding: Spacing.xs,
  },
  pickerContainer: {
    paddingHorizontal: Spacing.lg,
    paddingVertical: Spacing.md,
    alignItems: "center",
    justifyContent: "center",
  },
  modalFooter: {
    flexDirection: "row",
    paddingHorizontal: Spacing.lg,
    paddingVertical: Spacing.md,
    borderTopWidth: 1,
    borderTopColor: Colors.borderLight,
    gap: Spacing.sm,
  },
  footerBtnSecondary: {
    flex: 1,
    paddingVertical: Spacing.sm,
    alignItems: "center",
    borderRadius: Layout.borderRadius.sm,
    backgroundColor: Colors.backgroundSecondary,
  },
  footerBtnSecondaryText: {
    fontSize: 14,
    fontWeight: "500",
    color: Colors.textSecondary,
  },
  footerBtnPrimary: {
    flex: 1,
    paddingVertical: Spacing.sm,
    alignItems: "center",
    borderRadius: Layout.borderRadius.sm,
    backgroundColor: Colors.primary,
  },
  footerBtnPrimaryText: {
    fontSize: 14,
    fontWeight: "600",
    color: "#FFFFFF",
  },
});

