import React from 'react';
import type { FieldSpec } from '../api';

interface SheetProps {
  fields: FieldSpec[];
  values: Record<string, string>;
  onChange: (id: string, value: string) => void;
  disabled?: boolean;
}

export const Sheet: React.FC<SheetProps> = ({ fields, values, onChange, disabled }) => {
  if (!fields || fields.length === 0) {
    return <p className="muted">В этой задаче нет полей для ввода ответов.</p>;
  }

  return (
    <div className="sheet-fields" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      {fields.map((f) => {
        const fieldKind = f.kind || f.type;
        const val = values[f.id] ?? '';

        return (
          <div key={f.id} className="field-group" style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <label style={{ fontWeight: 600, fontSize: '14px' }}>
              {f.label || f.id} {f.unit ? <span className="muted">({f.unit})</span> : null}
            </label>

            {fieldKind === 'choice' && Array.isArray(f.options) ? (
              <select
                value={val}
                disabled={disabled}
                onChange={(e) => onChange(f.id, e.target.value)}
                style={{ padding: '8px', borderRadius: '4px', border: '1px solid #ccc' }}
              >
                <option value="">-- Выберите вариант --</option>
                {f.options.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type="text"
                value={val}
                disabled={disabled}
                placeholder={f.hint || ''}
                onChange={(e) => onChange(f.id, e.target.value)}
                style={{ padding: '8px', borderRadius: '4px', border: '1px solid #ccc' }}
              />
            )}
          </div>
        );
      })}
    </div>
  );
};
