"use client";

import { useState, useRef, useCallback } from "react";

export default function DropZone({ onFileUploaded, onFilesUploaded }) {
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [fileName, setFileName] = useState("");
  const [thumbnail, setThumbnail] = useState(null);
  const [fileInfo, setFileInfo] = useState(null);
  const [mediaType, setMediaType] = useState(null);
  const [error, setError] = useState(null);
  const fileRef = useRef(null);

  const handleFile = useCallback(
    async (fileOrFiles) => {
      var files = Array.isArray(fileOrFiles) ? fileOrFiles : [fileOrFiles];
      files = files.filter(Boolean);
      var uploaded = [];
      for (var file of files) {
      if (!file) return;
      setError(null);
      setUploading(true);
      setFileName(file.name);

      try {
        // Upload file
        const formData = new FormData();
        formData.append("file", file);

        const uploadRes = await fetch("/api/upload", {
          method: "POST",
          body: formData,
        });

        if (!uploadRes.ok) {
          const err = await uploadRes.json().catch(() => ({}));
          throw new Error(err.error || "Upload failed");
        }

        const uploadData = await uploadRes.json();

        // Extract thumbnail + get info
        const thumbRes = await fetch("/api/thumbnail", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ filename: uploadData.filename }),
        });

        if (!thumbRes.ok) {
          throw new Error("Thumbnail extraction failed");
        }

        const thumbData = await thumbRes.json();
        setThumbnail(thumbData.thumbnail + "?t=" + Date.now());
        setFileInfo(thumbData.info);
        setMediaType(thumbData.mediaType || uploadData.mediaType);

        var uploadedFile = {
          filename: uploadData.filename,
          path: uploadData.path,
          info: thumbData.info,
          mediaType: thumbData.mediaType || uploadData.mediaType,
        };
        uploaded.push(uploadedFile);
        if (uploaded.length === 1) onFileUploaded(uploadedFile);
      } catch (err) {
        setError(err.message);
      } finally {
        setUploading(false);
      }
      }
      if (uploaded.length && onFilesUploaded) onFilesUploaded(uploaded);
    },
    [onFileUploaded, onFilesUploaded]
  );

  const onDragOver = (e) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const onDragLeave = () => setIsDragging(false);

  const onDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    const files = Array.from(e.dataTransfer.files || []).filter((file) => file.type.startsWith("video/") || file.type.startsWith("image/"));
    if (files.length) {
      handleFile(files);
    }
  };

  const formatSize = (bytes) => {
    if (bytes > 1e9) return (bytes / 1e9).toFixed(1) + " GB";
    if (bytes > 1e6) return (bytes / 1e6).toFixed(1) + " MB";
    return (bytes / 1e3).toFixed(0) + " KB";
  };

  const formatDuration = (seconds) => {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
  };

  return (
    <div
      onClick={() => fileRef.current?.click()}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      className={`
        relative cursor-pointer rounded-card border transition-all duration-300
        ${isDragging ? "border-purple bg-purple-glow" : "border-border hover:border-border-hover"}
        ${thumbnail ? "p-4" : "p-10"}
        bg-card
      `}
    >
      <input
        ref={fileRef}
        type="file"
        multiple
        accept="video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm,image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp"
        onChange={(e) => handleFile(Array.from(e.target.files || []))}
        className="hidden"
      />

      {uploading ? (
        <div className="text-center py-4">
          <div className="text-sm text-purple animate-pulse font-mono">
            Processing...
          </div>
          <div className="text-xs text-muted-dark mt-2">{fileName}</div>
        </div>
      ) : thumbnail ? (
        <div className="flex gap-4 items-center">
          <img
            src={thumbnail}
            alt="Preview"
            className="w-24 h-auto rounded-lg border border-border"
          />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <div className="text-sm text-purple truncate font-mono">
                {fileName}
              </div>
              {mediaType && (
                <span className={`text-[9px] px-1.5 py-0.5 rounded-full font-mono uppercase tracking-wider ${
                  mediaType === "image"
                    ? "bg-amber/10 text-amber border border-amber-dim"
                    : "bg-purple/10 text-purple border border-purple-dim"
                }`}>
                  {mediaType}
                </span>
              )}
            </div>
            {fileInfo && (
              <div className="flex flex-wrap gap-3 mt-2">
                <span className="text-xs text-muted-dark font-mono">
                  {fileInfo.width}x{fileInfo.height}
                </span>
                {mediaType === "video" && fileInfo.duration > 0 && (
                  <span className="text-xs text-muted-dark font-mono">
                    {formatDuration(fileInfo.duration)}
                  </span>
                )}
                <span className="text-xs text-muted-dark font-mono">
                  {formatSize(fileInfo.size)}
                </span>
                <span className="text-xs text-muted-dark font-mono uppercase">
                  {fileInfo.codec}
                </span>
              </div>
            )}
            <div className="text-[10px] text-muted-darker mt-1">
              click to change
            </div>
          </div>
        </div>
      ) : (
        <div className="text-center">
          <div className="text-4xl mb-3 opacity-30">{"\u2B21"}</div>
          <div className="text-sm text-muted">
            Drop file here or click to select
          </div>
          <div className="text-xs text-muted-darker mt-1">
            mp4 {"\u00B7"} mov {"\u00B7"} webm {"\u00B7"} jpg {"\u00B7"} png {"\u00B7"} webp
          </div>
        </div>
      )}

      {error && (
        <div className="text-xs text-red-400 mt-2 text-center">{error}</div>
      )}
    </div>
  );
}
