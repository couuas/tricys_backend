import numpy as np

def lttb_downsample(data: np.ndarray, n_out: int) -> np.ndarray:
    """
    Pure Python/Numpy implementation of Largest Triangle Three Buckets algorithm.
    Optimized with vectorized area calculations.
    
    data: numpy array of shape (N, 2) where column 0 is X and column 1 is Y.
    n_out: number of points to return.
    """
    n_in = len(data)
    if n_out >= n_in or n_out <= 2:
        return data

    # Pre-allocate output
    out = np.zeros((n_out, 2))
    
    # Always add the first point
    out[0] = data[0]
    
    # Bucket size (excluding first and last points)
    every = (n_in - 2) / (n_out - 2)
    
    for i in range(n_out - 2):
        # Calculate range for current bucket
        avg_range_start = int(np.floor((i + 1) * every) + 1)
        avg_range_end = int(np.floor((i + 2) * every) + 1)
        avg_range_end = min(avg_range_end, n_in)
        
        # Average point of the next bucket
        avg_data = data[avg_range_start:avg_range_end]
        avg_x = np.mean(avg_data[:, 0])
        avg_y = np.mean(avg_data[:, 1])
        
        # Range for current bucket
        range_start = int(np.floor(i * every) + 1)
        range_end = int(np.floor((i + 1) * every) + 1)
        
        # Point from previous bucket
        prev_x, prev_y = out[i]
        
        current_bucket = data[range_start:range_end]
        
        # Vectorized area calculation: 0.5 * |x1(y2-y3) + x2(y3-y1) + x3(y1-y2)|
        areas = 0.5 * np.abs(
            prev_x * (current_bucket[:, 1] - avg_y) +
            current_bucket[:, 0] * (avg_y - prev_y) +
            avg_x * (prev_y - current_bucket[:, 1])
        )
        
        max_idx = np.argmax(areas)
        out[i+1] = current_bucket[max_idx]
        
    # Always add the last point
    out[-1] = data[-1]
    
    return out