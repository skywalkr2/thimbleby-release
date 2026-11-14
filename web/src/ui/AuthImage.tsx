import { useEffect, useRef, type ImgHTMLAttributes } from "react";
import { useBlobUrl } from "../lib/authed-file";

/** A picture the server keeps behind the session (the workspace's logo, a file's preview). It is drawn once its bytes
 *  have arrived; if they can't be had, `onError` is called as a picture that failed to load would. */
export function AuthImage(props: Omit<ImgHTMLAttributes<HTMLImageElement>, "src"> & { src: string }) {
  const { src, onError, ...rest } = props;
  const url = useBlobUrl(src);
  const failed = useRef(onError);
  failed.current = onError;
  useEffect(() => {
    if (url === null) failed.current?.(new Event("error") as never);
  }, [url]);
  if (!url) return null;
  return <img {...rest} src={url} onError={onError} />;
}
